import unittest
from simulator.fleet_continuation import clone_world
from simulator.orchard_care import OrchardCare

class ContinuationTests(unittest.TestCase):
    def test_explicit_fallback_refresh_updates_parent_and_worker_preserving_evidence(self):
        import copy
        from unittest.mock import patch,Mock
        from simulator.fleet_care import FleetCareWorld,FleetCareRuntime
        from simulator.treatment_runtime import TreatmentRuntime
        from simulator.fleet_continuation import continue_fleet
        parent=FleetCareWorld();parent.status='paused'
        worker=OrchardCare(parent.seed,1,'W1',parent.tasks[0]);worker.status='paused'
        worker.moisture=65;worker.care_completed={'irrigation':{'frame_id':'old-evidence'}}
        parent.assignments={'0':dict(vehicle='W1',status='assigned',session_id=worker.id)}
        old=dict(after_failures=1,engine='gemini',provider_base='https://ai-gateway.vercel.sh/v1',models={'treatment':'google/gemini-2.5-flash'})
        config=dict(mode='vision',engine='crusoe',fallback=old)
        inference=[dict(cost=.01,requested_model='google/gemini-2.5-flash')]
        saved=parent.checkpoint();saved['runtime_state']=dict(config=config)
        child_saved=worker.checkpoint();child_saved['runtime_state']=dict(config=config,inference=inference,provider_routes={'treatment':{'fallback':True}},active_wall=22)
        repo=Mock();repo.restore.side_effect=lambda sid:copy.deepcopy({parent.id:saved,worker.id:child_saved}[sid])
        with patch('threading.Thread.start'),patch.object(FleetCareRuntime,'persist',return_value=True),patch.object(TreatmentRuntime,'persist',return_value=True):
            runtime=continue_fleet(repo,parent.id,'User requested latest Gemini',refresh_fallback=True)
        try:
            child=runtime.children['W1']
            for r in (runtime,child):
                self.assertEqual(r.config['fallback']['models']['treatment'],'google/gemini-4-argon')
                self.assertTrue(any(e['type']=='fallback_policy_updated' for e in r.world.events))
            self.assertEqual(child.adapter('treatment').model,'google/gemini-4-argon')
            self.assertEqual(child.inference,inference);self.assertEqual(child.active_wall,22)
            self.assertEqual(child.world.moisture,65);self.assertEqual(child.world.care_completed,worker.care_completed)
            self.assertEqual(child_saved['runtime_state']['config']['fallback'],old)
        finally:runtime.close()
        saved['status']='running';child_saved['status']='running'
        with self.assertRaisesRegex(ValueError,'paused or terminal'):
            continue_fleet(repo,parent.id,'ordinary continuation cannot take a live writer')
        with patch('threading.Thread.start'),patch.object(FleetCareRuntime,'persist',return_value=True),patch.object(TreatmentRuntime,'persist',return_value=True),patch('simulator.background_storage.local_restart_checkpoint',side_effect=lambda repo,sid:repo.restore(sid)):
            runtime=continue_fleet(repo,parent.id,'local server restart',interrupted=True)
            runtime.start()
        try:
            self.assertEqual(runtime.world.status,'running')
            self.assertEqual(runtime.children['W1'].world.status,'running')
            self.assertEqual(runtime.children['W1'].inference,inference)
        finally:runtime.close()
        child_saved['runtime_state']['pending_requests']={'W1':{'id':'unsettled'}}
        with patch('simulator.background_storage.local_restart_checkpoint',side_effect=lambda repo,sid:repo.restore(sid)),self.assertRaisesRegex(ValueError,'accounting'):
            continue_fleet(repo,parent.id,'local restart with unsettled accounting',interrupted=True)

    def test_new_identity_preserves_physical_state_and_evidence(self):
        w=OrchardCare();w.status='paused';w.robot['battery']=87;w.moisture=65;w.effective=21
        w.care_completed={'irrigation':dict(frame_id='saved-frame',revision=12)}
        w.frames=[dict(id='saved-frame',task_index=0,extracted=False)]
        w.frame=dict(id='saved-frame');w.decisions=18;w.time=40
        saved=w.checkpoint();saved['runtime_state']=dict(config=dict(treatment_code_hash='source-hash'),pending_requests={})
        clone=clone_world(saved,OrchardCare,w.id,'Improve descent feedback')
        self.assertNotEqual(clone.id,w.id);self.assertEqual(clone.robot,w.robot)
        self.assertEqual(clone.moisture,65);self.assertEqual(clone.care_completed,w.care_completed)
        self.assertEqual(clone.frames,w.frames);self.assertEqual(clone.decisions,18);self.assertEqual(clone.time,40)
        self.assertIsNone(clone.frame);self.assertEqual(clone.continuation_source['implementation_hash'],'source-hash')
        self.assertTrue(clone.verify()['inventory']);self.assertEqual(saved['id'],w.id)

    def test_pending_accounting_or_damage_cannot_be_erased(self):
        w=OrchardCare();saved=w.checkpoint();saved['runtime_state']=dict(pending_requests={'W1':{}})
        with self.assertRaisesRegex(ValueError,'accounting'):clone_world(saved,OrchardCare,w.id,'test')
        saved['runtime_state']['pending_requests']={};saved['damage']=['clover']
        with self.assertRaisesRegex(ValueError,'damage'):clone_world(saved,OrchardCare,w.id,'test')
        continued=clone_world(saved,OrchardCare,w.id,'restart to return damaged attempt for service',retain_damage=True)
        self.assertEqual(continued.damage,['clover']);self.assertFalse(continued.verify()['preserved'])

    def test_continuation_keeps_worker_provider_pins_and_closes_failed_child(self):
        import copy
        from unittest.mock import patch,Mock
        from simulator.fleet_care import FleetCareWorld,FleetCareRuntime
        from simulator.treatment_runtime import TreatmentRuntime
        from simulator.fleet_continuation import continue_fleet
        parent=FleetCareWorld();parent.status='paused'
        worker=OrchardCare(parent.seed,1,'W1',parent.tasks[0]);worker.status='paused';worker.wall_limit=900;worker.cost_limit=1
        parent.assignments={'0':dict(vehicle='W1',status='assigned',session_id=worker.id)}
        parent.worker_sessions={worker.id:dict(task_index=0,worker='W1')}
        config=dict(mode='vision',engine='crusoe',models={'treatment':'parent-model'},provider_base='parent-provider')
        child_config=dict(config,models={'treatment':'worker-model'},provider_base='worker-provider',fallback={'models':{'treatment':'pinned-fallback'},'provider_base':'fallback-provider','after_failures':2,'engine':'gemma'})
        saved=parent.checkpoint();saved['runtime_state']=dict(config=config)
        child_saved=worker.checkpoint();child_saved['runtime_state']=dict(config=child_config,provider_routes={'W1':{'fallback':True}})
        repo=Mock();repo.restore.side_effect=lambda sid:copy.deepcopy({parent.id:saved,worker.id:child_saved}[sid])
        with patch('threading.Thread.start'),patch.object(FleetCareRuntime,'persist',return_value=True),patch.object(TreatmentRuntime,'persist',return_value=True):
            runtime=continue_fleet(repo,parent.id,'test')
        try:
            child=runtime.children['W1']
            for key in ('models','provider_base','fallback'):self.assertEqual(child.config[key],child_config[key])
            self.assertEqual(child.config['parent_session_id'],runtime.world.id)
            self.assertEqual(child.world.wall_limit,parent.contract['wall_limit'])
            self.assertEqual(child.world.cost_limit,parent.contract['cost_limit'])
            self.assertTrue(child.provider_routes['W1']['fallback'])
        finally:runtime.close()
        created=[]
        original=FleetCareRuntime.make_child
        def track(runtime,*args):
            child=original(runtime,*args);created.append(child);return child
        with patch('threading.Thread.start'),patch.object(FleetCareRuntime,'make_child',track),patch.object(TreatmentRuntime,'persist',return_value=False):
            with self.assertRaisesRegex(ValueError,'checkpoint'):continue_fleet(repo,parent.id,'test')
        self.assertEqual(len(created),1);self.assertTrue(created[0].closed)

    def test_miss_requires_new_view_but_slip_regrasp_remains_available(self):
        from simulator.manipulation import Manipulation
        from simulator.arm import ik
        w=Manipulation(7,'precision');w.nonempty_scan=True
        w.joints=ik([0,.13,1.6,0,0,0],w.base())
        w.missed_grasp=dict(position=[0,.13,1.6],revision=0,force=30)
        self.assertEqual(w.allowed_actions(),['move_arm','stop'])
        self.assertIn('wide_view_pose',w.observations()['current_grasp_step'])
        w.joints=ik([0,.8,2.2,0,0,0],w.base())
        self.assertIn('scan_lidar',w.allowed_actions());self.assertNotIn('assess_alignment',w.allowed_actions())
        w.missed_grasp=None;w.joints=ik([0,.13,1.6,0,0,0],w.base())
        self.assertIn('assess_alignment',w.allowed_actions())
