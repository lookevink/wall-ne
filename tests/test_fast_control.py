"""The fast controller sees exactly the policy projection, never simulator targets."""
import unittest
from unittest.mock import patch
from simulator.orchard_care import OrchardCare
from simulator.camera import project_pixel, project_ground
from simulator.common import uid
from tests.test_treatment import frame
from simulator.fast_control import automatic_action, vision_observation


class FastControlTests(unittest.TestCase):
    def settle(self,w):
        for _ in range(12000):
            if not w.robot['action']:return
            w.tick(.05)
        self.fail('motion did not settle')

    def act(self,w,action,args):
        r=w.command(uid(),w.robot['id'],action,**args)
        self.assertTrue(r['accepted'],r)
        self.settle(w)

    def test_complete_tree_with_six_visual_decisions_and_real_physical_checks(self):
        w=OrchardCare(tree_count=1);w.status='running';w.begin();self.settle(w)
        visual=[];automatic=[]
        for _ in range(70):
            if w.status=='completed':break
            if not w.frame or w.frame['revision']!=w.revision or w.frame['phase']!=w.phase:frame(w)
            obs=w.observations();decision=automatic_action(obs)
            if decision:
                action,args=decision;automatic.append(action)
            else:
                obs=vision_observation(obs);actions=obs['available_actions']
                # Synthetic oracle only in this test: live decisions must use RGB.
                if w.phase=='pests':
                    remaining=[p for p in w.pests if not p['removed']]
                    action='remove_pest' if remaining else 'next_stage'
                    args=dict(zip(('u','v'),project_pixel(w.camera(),remaining[0]['position']))) if remaining else {}
                elif 'scan_lidar' in actions:action='scan_lidar';args=dict(zip(('u','v'),project_pixel(w.camera(),w.weed['position'])));args['span']=.16
                elif 'project_ground' in actions and 'assess_alignment' not in actions:action='project_ground';args=dict(zip(('u','v'),project_pixel(w.camera(),w.weed['position'])))
                else:action='assess_alignment';args=dict(stem_between_fingers=True,depth_consistent=True,evidence='Synthetic oracle sees both finger faces and the stem')
                args['frame_id']=w.frame['id'];visual.append(action)
            self.act(w,action,args)
            if w.depth_request:
                req=w.depth_request;points=[[u,v,*project_ground(req['camera'],u,v)] for u,v in req['rays']]
                w.accept_depth(req['id'],req['frame_id'],req['revision'],points,dict(id='test-depth',ready=True))
        self.assertEqual(w.status,'completed',w.feedback)
        self.assertTrue(all(w.verify().values()),w.verify())
        self.assertLessEqual(len(visual),6,visual)
        self.assertIn('confirm_contact',automatic)
        self.assertIn('read_moisture',automatic)
        self.assertNotIn('assess_alignment',automatic)

    def test_no_target_truth_and_no_automatic_visual_alignment(self):
        w=OrchardCare(tree_count=1);w.status='running';w.begin();self.settle(w);frame(w)
        obs=w.observations();first=automatic_action(obs)
        w.weed['position']=[99,.08,99];w.pests=[]
        self.assertEqual(automatic_action(obs),first)
        self.assertNotIn('weed',vision_observation(obs))
        w.phase='extraction';w.nonempty_scan=True;w.crown_projection={'world':{'x':0,'y':.08,'z':1},'revision':w.revision};frame(w)
        obs=w.observations();obs['tool_pose']['position']=[0,.13,1];obs['available_actions']+=['assess_alignment']
        self.assertIsNone(automatic_action(obs))
        self.assertIn('assess_alignment',vision_observation(obs)['available_actions'])

    def test_measured_miss_reopens_before_recovery(self):
        w=OrchardCare(tree_count=1);w.phase='extraction';w.status='running';w.nonempty_scan=True;w.must_reopen=True;w.opening=0;frame(w)
        self.assertEqual(automatic_action(w.observations())[0],'open_gripper')

    def test_false_alignment_cannot_close_and_contact_requires_load(self):
        w=OrchardCare(tree_count=1);w.phase='extraction';w.status='running';w.nonempty_scan=True;frame(w)
        obs=w.observations();obs['protocol']['alignment']={'aligned':False};obs['tool_pose']['position']=[0,.13,1];obs['available_actions']+=['assess_alignment']
        self.assertIsNone(automatic_action(obs))
        obs['gripper'].update(holding=True,load=0)
        self.assertIsNone(automatic_action(obs))

    def test_fast_runtime_runs_routine_action_without_model_and_stops_on_bad_motion(self):
        from simulator.treatment_runtime import TreatmentRuntime
        w=OrchardCare(tree_count=1);w.status='running';w.begin();self.settle(w);frame(w)
        with patch('threading.Thread.start'):
            runtime=TreatmentRuntime(w,config=dict(mode='vision',engine='crusoe',care_controller='ultra_fast',speed=16))
        self.addCleanup(runtime.close)
        with patch.object(runtime,'persist',return_value=True),patch.object(runtime,'dispatch') as dispatch:
            runtime.step(.05)
        self.assertEqual(w.phase,'irrigation');dispatch.assert_not_called()
        self.assertEqual(runtime.adapter('treatment').timeout,6)
        self.assertEqual(runtime.adapter('treatment').max_tokens,512)
        self.assertEqual(runtime.config['fallback']['after_failures'],1)

    def test_fast_scheduler_launches_all_five_without_model(self):
        from simulator.fleet_care import FleetCareRuntime
        with patch('threading.Thread.start'):
            runtime=FleetCareRuntime(config=dict(mode='vision',engine='crusoe',care_controller='ultra_fast',speed=16))
        self.addCleanup(runtime.close);runtime.world.status='running'
        with patch.object(runtime,'persist',return_value=True),patch.object(runtime,'dispatch') as dispatch:
            runtime.step(.05)
        self.assertEqual(len(runtime.world.assignments),5)
        self.assertEqual({a['vehicle'] for a in runtime.world.assignments.values()},{'W1','W2','W3','W4','W5'})
        dispatch.assert_not_called()

    def test_named_vision_tools_resolve_only_current_pixel_candidates(self):
        import json
        from simulator.inference import Adapter,InferenceError
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(self.body).encode()
        reply=Reply();reply.body={'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'scan_lidar','arguments':json.dumps(dict(frame_id='fresh',candidate_id='c1',span=.16,reason='Visible pointed weed root'))}}]}}]}
        a=Adapter('crusoe');a.key='test';a.max_tokens=512
        obs=dict(controller='ultra_fast',trial='precision',phase='extraction',frame={'id':'fresh'},available_actions=['scan_lidar','stop'],pixel_candidates=[dict(id='c1',u=.4,v=.7,area=20,bounds=[.3,.5,.5,.75])])
        with patch('urllib.request.urlopen',return_value=reply) as send:
            result=a.call(obs,'data:image/png;base64,test')
        payload=json.loads(send.call_args[0][0].data)
        self.assertEqual([t['function']['name'] for t in payload['tools']],['scan_lidar','stop'])
        self.assertEqual(payload['max_tokens'],512)
        self.assertEqual(result['decision']['arguments'],dict(frame_id='fresh',span=.16,u=.4,v=.7))
        reply.body['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps(dict(frame_id='fresh',candidate_id='unknown',span=.16,reason='Visible root'))
        with patch('urllib.request.urlopen',return_value=reply):
            with self.assertRaises(InferenceError):a.call(obs)

    def test_heartbeat_does_not_duplicate_motion_artifact_samples(self):
        from simulator.telemetry import Telemetry
        w=OrchardCare(tree_count=1);t=Telemetry()
        t.sample(w,0);count=len(t.motion)
        t.sample(w,0,heartbeat=True)
        self.assertEqual(len(t.motion),count)
        self.assertTrue(t.history[w.robot['id']])
        self.assertEqual(w.events[-1]['type'],'heartbeat')

    def test_busy_worker_does_not_block_fleet_snapshot_or_spend_accounting(self):
        import threading
        from simulator.fleet_care import FleetCareRuntime
        with patch('threading.Thread.start'):
            r=FleetCareRuntime(config=dict(mode='vision',engine='crusoe',care_controller='ultra_fast'))
            child=r.make_child(0,'W1')
        self.addCleanup(r.close);r.children={'W1':child};child.operator_snapshot=child.snapshot()
        r.world.status='running';r.world.assignments={'0':dict(vehicle='W1',status='assigned',session_id=child.world.id)}
        locked=threading.Event();release=threading.Event()
        def hold():
            with child.lock:locked.set();release.wait(2)
        thread=threading.Thread(target=hold);thread.start();locked.wait(1)
        try:
            with patch.object(r,'persist',return_value=True):r.sync_workers()
            snapshot=r.snapshot()
            self.assertEqual(snapshot['care_workers']['W1']['id'],child.world.id)
            self.assertFalse(release.is_set())
        finally:release.set();thread.join()
