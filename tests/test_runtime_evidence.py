import concurrent.futures
import unittest
from unittest.mock import Mock,patch
from simulator.runtime import Runtime
from simulator.treatment_runtime import TreatmentRuntime
from simulator.engine import Mission
from simulator.manipulation import Manipulation
from tests.test_treatment import frame
from tests.test_recovery import SavedRepository

class RuntimeEvidenceTests(unittest.TestCase):
    def runtime(self,world=None,cls=Runtime):
        with patch('threading.Thread.start'):
            runtime=cls(world=world or Mission(),config=dict(mode='vision' if cls==TreatmentRuntime else 'live',engine='gemini',capture_training_inputs=False))
        self.addCleanup(runtime.close)
        return runtime

    def future(self,cost=.1,action='verify'):
        future=concurrent.futures.Future();future.set_result(dict(id='decision',decision=dict(action=action,arguments={}),usage={},cost=cost));return future

    def test_spend_crossing_response_never_executes(self):
        w=Manipulation();w.status='running';frame(w)
        runtime=self.runtime(w,TreatmentRuntime);runtime.futures['T1']=(w.id,self.future(1.5))
        with patch.object(runtime,'persist',return_value=True),patch.object(w,'command') as command:
            runtime.step(.1)
        command.assert_not_called();self.assertEqual(w.status,'blocked');self.assertEqual(runtime.inference[0]['cost'],1.5)

    def test_terminal_observations_are_rejected_before_upload(self):
        w=Manipulation();w.request_frame();w.status='blocked';runtime=self.runtime(w,TreatmentRuntime)
        with patch.object(runtime.repository,'artifact') as upload:
            for method in (runtime.accept_frame,runtime.accept_depth):
                with self.assertRaisesRegex(ValueError,'terminal'):method({'mission_id':w.id})
            upload.assert_not_called()

    def test_requests_commit_before_dispatch_and_failed_commit_blocks_call(self):
        runtime=self.runtime();runtime.world.status='running';adapter=Mock(model='fake');adapter.call.return_value=dict(usage={},cost=.1)
        observations=[]
        def persist():
            observations.append(runtime.world.events[-1]['type']);return False
        with patch.object(runtime,'adapter',return_value=adapter),patch.object(runtime,'persist',side_effect=persist):
            self.assertFalse(runtime.dispatch('planner','planner',{'frame_id':'frame'}))
        self.assertEqual(observations,['inference_requested']);adapter.call.assert_not_called()
        with patch.object(runtime,'adapter',return_value=adapter),patch.object(runtime,'persist',return_value=True):
            self.assertTrue(runtime.dispatch('planner','planner',{}))
        result=runtime.futures['planner'][1].result(timeout=2)
        self.assertEqual(result['request_id'],runtime.requests['planner']['id'])

    def test_later_completed_response_is_accounted_after_first_blocks(self):
        runtime=self.runtime();w=runtime.world;w.status='running';runtime.failures['planner']=2
        runtime.futures={'planner':(w.id,self.future(.2,'wrong')),'W1':(w.id,self.future(.3))}
        with patch.object(runtime,'persist',return_value=True):runtime._live()
        self.assertEqual(w.status,'blocked');self.assertEqual(sum(r['cost'] for r in runtime.inference),.5);self.assertFalse(runtime.futures)

    def test_restore_pending_request_is_explicitly_unknown_and_does_not_reissue(self):
        w=Mission();w.runtime_state={'pending_requests':{'planner':{'id':'lost-request'}}}
        repo=SavedRepository(w,dict(mode='live',engine='gemini',models={'planner':'fake'},provider_base='test'))
        runtime=self.runtime();runtime.repository=repo
        with patch.object(runtime,'persist',return_value=True):runtime.restore(w.id)
        self.assertEqual(runtime.inference[0]['request_id'],'lost-request');self.assertIsNone(runtime.inference[0]['cost']);self.assertFalse(runtime.futures)

    def test_restore_waits_for_original_session_accounting(self):
        runtime=self.runtime();runtime.futures['planner']=(runtime.world.id,concurrent.futures.Future())
        with self.assertRaisesRegex(ValueError,'outstanding'):runtime.restore('another')

    def test_superseded_scan_cannot_claim_new_frame_as_crop_source(self):
        from simulator import lidar
        w=Manipulation();w.status='running';first=frame(w)
        w.depth_request=lidar.request(first,.5,.5)
        request=w.depth_request.copy();frame(w) # Same revision, different captured frame.
        runtime=self.runtime(w,TreatmentRuntime)
        with patch.object(runtime.repository,'artifact') as upload:
            with self.assertRaisesRegex(ValueError,'superseded'):
                runtime.accept_depth(dict(mission_id=w.id,request_id=request['id'],frame_id=first['id'],revision=w.revision,points=[None]*169))
            upload.assert_not_called()
        self.assertEqual(w.depth_request,request);self.assertIsNone(w.scan)
