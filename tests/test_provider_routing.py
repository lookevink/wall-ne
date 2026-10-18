import concurrent.futures
import unittest
from unittest.mock import patch
from simulator.runtime import Runtime
from simulator.treatment_runtime import TreatmentRuntime
from simulator.manipulation import Manipulation
from simulator.inference import InferenceError,Adapter
from tests.test_treatment import frame

class ProviderRoutingTests(unittest.TestCase):
    def test_latest_gemini_uses_supported_reasoning_for_fast_tools(self):
        from simulator.inference import build_request,MODELS
        observation=dict(controller='ultra_fast',available_actions=['stop'])
        body=build_request(observation,None,'test',MODELS['gemini'],max_tokens=2048,provider='gateway')
        self.assertEqual(body['reasoning'],{'effort':'low'})
        self.assertEqual(body['max_tokens'],2048)
        self.assertEqual(body['tools'][0]['function']['name'],'stop')
        legacy=build_request(observation,None,'test','google/gemini-2.5-flash',provider='gateway')
        self.assertEqual(legacy['reasoning'],{'enabled':False})

    def test_stale_standard_settings_use_fast_control_and_switch_after_first_429(self):
        from simulator.fleet_care import FleetCareWorld,FleetCareRuntime
        with patch('threading.Thread.start'),patch.dict('os.environ',{'WALLNE_GATEWAY_FALLBACK':'0'}):
            parent=FleetCareRuntime(FleetCareWorld(tree_count=169),config=dict(mode='vision',engine='crusoe',care_controller='standard'))
            child=parent.make_child(0,'W1')
        self.addCleanup(parent.close);self.addCleanup(child.close)
        self.assertEqual(parent.config['care_controller'],'ultra_fast')
        self.assertIsNotNone(parent.config['fallback'])
        self.assertEqual(child.config['fallback'],parent.config['fallback'])
        for runtime,robot,role,model in ((parent,'orchestrator','orchestrator','nvidia/nemotron-3-super-120b-a12b'),
                                        (child,'W1','treatment','google/gemini-4-argon')):
            runtime.world.status='running'
            adapter=runtime.adapter(role)
            runtime.requests[robot]=dict(id='request',role=role,provider=adapter.provider,provider_base=adapter.base,model=adapter.model,fallback=False)
            future=concurrent.futures.Future()
            future.set_exception(InferenceError('crusoe HTTP 429; no fallback performed',dict(status='failed',cost=0,usage={})))
            with self.assertRaises(InferenceError) as caught:runtime.consume(robot,future)
            self.assertTrue(caught.exception.fallback_activated)
            self.assertEqual(runtime.adapter(role).provider,'gateway')
            self.assertEqual(runtime.adapter(role).model,model)
            self.assertEqual(runtime.world.status,'running')

    def test_full_care_preserves_explicit_disabled_fallback(self):
        from simulator.fleet_care import FleetCareWorld,FleetCareRuntime
        with patch('threading.Thread.start'):
            runtime=FleetCareRuntime(FleetCareWorld(),config=dict(mode='vision',engine='crusoe',fallback=None))
        self.addCleanup(runtime.close)
        self.assertIsNone(runtime.config['fallback'])

    def test_saved_standard_full_care_cannot_restore_the_retired_controller(self):
        from simulator.fleet_care import FleetCareWorld,FleetCareRuntime
        from tests.test_recovery import SavedRepository
        with patch('threading.Thread.start'):
            runtime=FleetCareRuntime(FleetCareWorld(),config=dict(mode='vision',engine='crusoe'))
        self.addCleanup(runtime.close)
        runtime.repository=SavedRepository(runtime.world,{**runtime.config,'care_controller':'standard'})
        with patch.object(runtime.repository,'lease') as lease:
            with self.assertRaisesRegex(ValueError,'retired Standard control'):runtime.restore(runtime.world.id)
        lease.assert_not_called()

    def runtime(self,fallback=True):
        w=Manipulation(7,'precision');w.status='running';frame(w)
        # The Gateway fallback is opt-in; these routing tests exercise it explicitly.
        with patch('threading.Thread.start'),patch.dict('os.environ',{'WALLNE_GATEWAY_FALLBACK':'1' if fallback else '0'}):
            r=TreatmentRuntime(w,config=dict(mode='vision',engine='crusoe'))
        self.addCleanup(r.close)
        return r

    def test_fallback_is_off_by_default_and_failures_block_visibly(self):
        r=self.runtime(fallback=False)
        self.assertIsNone(r.config['fallback'])
        for index in range(3):
            r.futures['T1']=(r.world.id,self.response(r,True))
            with patch.object(r,'persist',return_value=True):r.step(.01)
            self.assertEqual(r.adapter('treatment').provider,'crusoe')
        self.assertEqual(r.world.status,'blocked')

    def response(self,r,error=False):
        a=r.adapter('treatment');future=concurrent.futures.Future()
        request=dict(id='request',role='treatment',provider=a.provider,provider_base=a.base,model=a.model,fallback=a.provider=='gateway')
        r.requests['T1']=request
        if error:future.set_exception(InferenceError('invalid tool call',dict(status='failed',cost=.02,usage={})))
        else:future.set_result(dict(decision=dict(action='stop',arguments={}),usage={},cost=.01))
        return future

    def test_two_consecutive_failures_switch_same_model_and_account_all_attempts(self):
        r=self.runtime()
        self.assertEqual(r.adapter('treatment').provider,'crusoe')
        for index in range(2):
            r.futures['T1']=(r.world.id,self.response(r,True))
            with patch.object(r,'persist',return_value=True):r.step(.01)
            self.assertEqual(r.adapter('treatment').provider,'gateway' if index else 'crusoe')
        self.assertEqual(r.world.status,'running');self.assertEqual(r.failures['T1'],0)
        self.assertEqual(r.adapter('treatment').model,'google/gemma-4-31b-it')
        self.assertEqual(sum(x['cost'] for x in r.inference),.04)
        self.assertEqual(sum(e['type']=='provider_fallback' for e in r.world.events),1)
        for _ in range(3):
            r.futures['T1']=(r.world.id,self.response(r,True))
            with patch.object(r,'persist',return_value=True):r.step(.01)
        self.assertEqual(r.world.status,'blocked');self.assertEqual(len(r.inference),5)

    def test_success_resets_streak_and_rejected_motion_does_not_switch(self):
        r=self.runtime()
        with self.assertRaises(InferenceError):r.consume('T1',self.response(r,True))
        r.consume('T1',self.response(r))
        with self.assertRaises(InferenceError):r.consume('T1',self.response(r,True))
        self.assertEqual(r.adapter('treatment').provider,'crusoe')
        for _ in range(3):
            future=self.response(r);future=concurrent.futures.Future()
            future.set_result(dict(decision=dict(action='move_arm',arguments=dict(pose=[0,.8,2.2,0,0,0])),usage={},cost=.01))
            r.futures['T1']=(r.world.id,future)
            with patch.object(r,'persist',return_value=True):r.step(.01)
        self.assertEqual(r.world.status,'blocked')
        self.assertFalse(r.provider_routes['treatment']['fallback'])

    def test_gateway_selection_and_terminal_errors_do_not_activate_fallback(self):
        r=self.runtime();r.world.status='blocked'
        for _ in range(3):
            with self.assertRaises(InferenceError):r.consume('T1',self.response(r,True))
        self.assertEqual(r.provider_routes,{})
        with patch('threading.Thread.start'):g=Runtime(config=dict(mode='live',engine='gemma'))
        self.addCleanup(g.close);self.assertNotIn('fallback',g.config)

    def test_fallback_route_survives_checkpoint_restore(self):
        from tests.test_recovery import SavedRepository
        r=self.runtime()
        for _ in range(2):
            with self.assertRaises(InferenceError):r.consume('T1',self.response(r,True))
        r.world.runtime_state=dict(provider_routes=r.provider_routes)
        repo=SavedRepository(r.world,r.config);r.repository=repo
        with patch.object(r,'persist',return_value=True):r.restore(r.world.id)
        self.assertEqual(r.adapter('treatment').provider,'gateway')
        self.assertEqual(r.config['fallback']['after_failures'],2)

    def test_malformed_provider_envelopes_are_accounted_failures(self):
        import json
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(self.value).encode()
        a=Adapter('crusoe');a.key='fake'
        for value in (None,[],{'usage':[]},{'usage':'bad'},{'usage':{'cost_details':[]},'choices':'bad'}):
            reply=Reply();reply.value=value
            with patch('urllib.request.urlopen',return_value=reply):
                with self.assertRaises(InferenceError) as caught:a.call({})
            self.assertEqual(caught.exception.metrics['status'],'failed')
            self.assertEqual(caught.exception.metrics['provider'],'crusoe')

    def test_changed_treatment_code_cannot_restore_under_old_pins(self):
        from tests.test_recovery import SavedRepository
        r=self.runtime();r.config['treatment_code_hash']='old-code'
        r.repository=SavedRepository(r.world,r.config)
        with self.assertRaisesRegex(ValueError,'implementation changed'):r.restore(r.world.id)

    def test_shared_worker_route_and_late_primary_do_not_spend_gateway_error_budget(self):
        with patch('threading.Thread.start'),patch.dict('os.environ',{'WALLNE_GATEWAY_FALLBACK':'1'}):r=Runtime(config=dict(mode='live',engine='crusoe'))
        self.addCleanup(r.close);r.world.status='running';r.world.planned=True
        def request(robot,fallback):
            r.requests[robot]=dict(id=robot,role='worker',model='test',provider='gateway' if fallback else 'crusoe',provider_base='test',fallback=fallback)
            f=concurrent.futures.Future();f.set_exception(InferenceError('provider error',dict(status='failed',cost=.01,usage={})));return f
        def consume(robot,fallback):
            with self.assertRaises(InferenceError) as error:r.consume(robot,request(robot,fallback))
            return error.exception.provider_failure_count
        self.assertEqual(consume('W1',False),1)
        self.assertEqual(consume('W2',False),0)
        self.assertTrue(r.provider_routes['worker']['fallback'])
        self.assertEqual(consume('W1',True),1)
        self.assertEqual(consume('W3',False),0) # late outstanding primary request
        self.assertEqual(r.provider_routes['worker']['failures'],1)
        self.assertEqual(consume('W1',True),2)
        self.assertEqual(consume('W1',True),3)
