"""Recoverable failures retain the task and its measured state until verified."""
import concurrent.futures
import copy
import time
import unittest
from unittest.mock import patch

from simulator.common import uid
from simulator.fleet_care import FleetCareRuntime
from simulator.inference import InferenceError
from simulator.orchard_care import OrchardCare
from simulator.treatment_runtime import TreatmentRuntime
from tests.test_treatment import frame


class CareHealingTests(unittest.TestCase):
    def test_preservation_failure_returns_to_service_without_claiming_success(self):
        r=self.runtime();w=r.world
        w.extracted=True;w.deposited=True;w.holding=False;w.nonempty_scan=True;w.inspection={'frame_id':'inspection'}
        for pest in w.pests:pest['removed']=True
        w.frames=[dict(id='before',task_index=0,extracted=False),dict(id='after',task_index=0,extracted=True,deposited=True)]
        w.damage=[w.protected[0]['id']];frame(w)
        self.assertTrue(all(v for k,v in w.task_checks().items() if k!='preserved'))
        receipt=w.command(uid(),w.robot['id'],'verify',frame_id=w.frame['id'])
        self.assertTrue(receipt['accepted'],receipt)
        self.assertEqual(w.phase,'return')
        self.assertFalse(w.completed_trees);self.assertFalse(w.task_exception['checks']['preserved'])
        for _ in range(2000):
            if w.status!='running':break
            w.tick(.1)
        self.assertEqual(w.status,'failed');self.assertTrue(w.return_verified)
        self.assertEqual(w.robot['position'],w.robot['home'])
        self.assertEqual(w.damage,[w.protected[0]['id']]);self.assertFalse(w.verify()['trees_complete'])

    def test_base_retreat_rejects_deeper_contact_and_new_obstacles(self):
        from simulator.arm import ik,base_retreat
        base=[0,.8,3.3];joints=ik([0,.8,2.2,0,0,0],base)
        self.assertGreater(base_retreat(joints,base,[[.1,2.2]],[-.65,0]),0)
        with self.assertRaisesRegex(ValueError,'deepens contact'):
            base_retreat(joints,base,[[.1,2.2]],[.65,0])
        with self.assertRaisesRegex(ValueError,'collision'):
            base_retreat(joints,base,[[.1,2.2],[-.5,2.2]],[-.65,0])

    def test_recovery_escapes_existing_trunk_overlap_without_resetting_care(self):
        from simulator.fleet_care import FleetCareWorld
        from simulator.arm import ik,trajectory
        task=FleetCareWorld(tree_count=169).tasks[13]
        w=OrchardCare(7,1,'W1',task);x,_,z=task['tree']['position']
        # The live failure: legacy interior parking carried the extended arm
        # through the neighboring trunk while only checking the chassis.
        w.robot['position']=[x,z+3.8]
        w.joints=ik([x,.8,z+2.2,0,0,0],w.base())
        w.status='running';w.phase='extraction';w.recovery={'stage':'viewpoint'};w.recovery_attempts=80
        w.moisture=65;w.fertilizer_effective=w.prescription;w.care_completed={'irrigation':{},'fertilizer':{}}
        frame(w)
        with self.assertRaisesRegex(ValueError,'trunk'):trajectory(w.joints,w.joints,w.base(),w.trunks)
        before=w.robot['position'][:];joints=w.joints[:]
        receipt=w.command(uid(),'W1','recover_view',frame_id=w.frame['id'])
        self.assertTrue(receipt['accepted'],receipt)
        self.assertEqual(w.robot['position'],before,'Planning must not teleport the robot')
        self.assertEqual(w.robot['action']['kind'],'recover_base')
        for _ in range(200):
            if not w.robot['action']:break
            w.tick(.05)
        self.assertIsNone(w.robot['action']);self.assertEqual(w.status,'running')
        self.assertNotEqual(w.robot['position'],before);self.assertEqual(w.joints,joints)
        trajectory(w.joints,w.joints,w.base(),w.trunks)
        self.assertEqual(w.moisture,65);self.assertEqual(w.fertilizer_effective,w.prescription)
        self.assertEqual(set(w.care_completed),{'irrigation','fertilizer'})

    def runtime(self):
        w=OrchardCare(tree_count=1);w.status='running';w.begin()
        while w.robot['action']:w.tick(.05)
        w.phase='extraction';w.care_completed={'irrigation':{},'fertilizer':{},'pests':{}}
        w.moisture=65;w.fertilizer_effective=w.prescription
        frame(w)
        with patch('threading.Thread.start'):
            r=TreatmentRuntime(w,config=dict(mode='vision',engine='crusoe',speed=16))
        self.addCleanup(r.close)
        r.persist=lambda:True
        return r

    def test_lost_depth_refreshes_camera_and_rejects_late_delivery(self):
        r=self.runtime();w=r.world
        self.assertTrue(w.command(uid(),'W1','scan_lidar',frame_id=w.frame['id'],u=.5,v=.6,span=.16)['accepted'])
        old=copy.deepcopy(w.depth_request);r.depth_started=time.monotonic()-31
        r.step(.05)
        self.assertEqual(w.status,'running')
        self.assertIsNone(w.depth_request)
        self.assertIsNotNone(w.frame_request)
        self.assertNotEqual(w.frame_request['id'],old['id'])
        self.assertEqual(w.moisture,65)
        with self.assertRaises(ValueError):r.accept_depth(dict(arena='orchard',mission_id=w.id,request_id=old['id'],frame_id=old['frame_id'],revision=old['revision'],points=[]))
        self.assertTrue(any(e['type']=='sensor_recovery' for e in w.events))

    def test_lost_camera_is_reissued_repeatedly_without_retiring_worker(self):
        r=self.runtime();w=r.world;w.frame=None
        for _ in range(5):
            old=w.request_frame()['id'];r.capture_started=time.monotonic()-31
            r.step(.05)
            self.assertEqual(w.status,'running')
            self.assertNotEqual(w.frame_request['id'],old)

    def test_model_stop_requests_physical_recovery_and_retains_completed_care(self):
        r=self.runtime();w=r.world;before=w.tool_pose()['position'][:]
        future=concurrent.futures.Future()
        future.set_result(dict(decision=dict(action='stop',arguments={'frame_id':w.frame['id']},rationale='No weed visible'),usage={},cost=0,latency=1))
        r.futures['W1']=(w.id,future)
        r.step(.05)
        self.assertEqual(w.status,'running')
        self.assertIsNotNone(w.recovery)
        from simulator.fast_control import vision_observation
        evidence=vision_observation(w.observations())['recovery_history']
        self.assertEqual(evidence[-1]['reason'],'No weed visible')
        self.assertNotIn('weed',evidence[-1])
        frame(w);r.step(.05)
        self.assertIsNotNone(w.robot['action'])
        self.assertEqual(w.tool_pose()['position'],before,'Recovery must move physically, never teleport')
        for _ in range(100):
            if not w.robot['action']:break
            r.step(.5)
        self.assertNotEqual(w.tool_pose()['position'],before)
        self.assertIsNone(w.recovery)
        self.assertEqual(w.moisture,65);self.assertEqual(w.fertilizer_effective,w.prescription)
        self.assertEqual(set(w.care_completed),{'irrigation','fertilizer','pests'})
        self.assertFalse(w.verify()['trees_complete'])
        self.assertTrue(any(e['type']=='recovery_completed' for e in w.events))

    def test_provider_outage_backoffs_without_failure_cutoff(self):
        r=self.runtime();w=r.world
        for _ in range(6):
            frame(w)
            future=concurrent.futures.Future()
            future.set_exception(InferenceError('provider unavailable',dict(status='failed',cost=0,usage={})))
            r.futures['W1']=(w.id,future)
            r.step(.05)
            self.assertEqual(w.status,'running')
        self.assertGreater(r.retry_after['W1'],time.monotonic())
        self.assertEqual(len(r.inference),6)

    def test_legacy_attempt_counts_do_not_end_continuous_care(self):
        r=self.runtime();w=r.world
        w.decisions=w.decision_limit;w.time=w.time_limit;w.frames=[{}]*w.frame_limit
        w.frame_request=None
        w.request_frame()
        receipt=w.command(uid(),'W1','capture_image')
        self.assertTrue(receipt['accepted'],receipt)
        self.assertEqual(w.status,'running')

    def test_explicit_operator_stop_still_stops(self):
        r=self.runtime()
        r.command('W1','stop',{'frame_id':r.world.frame['id']})
        self.assertEqual(r.world.status,'aborted')

    def test_fleet_does_not_impose_smaller_worker_budgets(self):
        with patch('threading.Thread.start'):
            r=FleetCareRuntime(config=dict(mode='vision',engine='crusoe'))
            child=r.make_child(0,'W1')
        self.addCleanup(r.close);self.addCleanup(child.close)
        self.assertEqual(child.world.wall_limit,r.world.contract['wall_limit'])
        self.assertEqual(child.world.cost_limit,r.world.contract['cost_limit'])

    def test_failed_attempt_continues_without_resetting_physics_or_losing_evidence(self):
        with patch('threading.Thread.start'):
            parent=FleetCareRuntime(config=dict(mode='vision',engine='crusoe'))
            old=parent.make_child(0,'W1')
        self.addCleanup(parent.close);parent.persist=lambda:True
        parent.world.status='running';parent.children['W1']=old;old.persist=lambda:True
        w=old.world;w.status='blocked';w.phase='extraction';w.feedback='depth request timed out'
        w.moisture=65;w.fertilizer_effective=w.prescription;w.pests[0]['removed']=True
        w.care_completed={'irrigation':{},'fertilizer':{}}
        assignment=dict(vehicle='W1',status='assigned',session_id=w.id)
        parent.world.assignments['0']=assignment
        parent.sync_workers();parent.schedule_recoveries()
        self.assertEqual(assignment['status'],'recovering')
        old_position=w.robot['position'][:];old_joints=w.joints[:]
        with patch('threading.Thread.start'):child=parent.make_recovery_child(assignment)
        self.addCleanup(child.close)
        self.assertNotEqual(child.world.id,w.id)
        self.assertEqual(child.config['continuation_source'],w.id)
        self.assertEqual(child.world.robot['position'],old_position)
        self.assertEqual(child.world.joints,old_joints)
        self.assertEqual(child.world.moisture,65)
        self.assertEqual(child.world.fertilizer_effective,w.prescription)
        self.assertTrue(child.world.pests[0]['removed'])
        self.assertEqual(w.status,'blocked','Old terminal evidence must stay immutable')
        self.assertIn(w.id,parent.world.results)
        self.assertFalse(parent.world.verify()['trees_complete'])

    def test_completed_retry_counts_once_despite_failed_attempt_history(self):
        with patch('threading.Thread.start'):parent=FleetCareRuntime(config=dict(mode='vision',engine='crusoe'))
        self.addCleanup(parent.close)
        for i in range(len(parent.world.tasks)):
            sid='success-'+str(i)
            parent.world.assignments[str(i)]=dict(vehicle='W'+str(i%5+1),status='completed',session_id=sid)
            parent.world.results[sid]=dict(status='completed',checks={'physical':True})
            parent.world.results['failed-'+str(i)]=dict(status='blocked',checks={'physical':False})
        self.assertTrue(parent.world.verify()['trees_complete'])
        parent.world.results['success-0']['checks']['physical']=False
        self.assertFalse(parent.world.verify()['trees_complete'])
