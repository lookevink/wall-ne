import unittest
from simulator.fleet_continuation import clone_world
from simulator.orchard_care import OrchardCare

class ContinuationTests(unittest.TestCase):
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

    def test_continuation_keeps_worker_provider_pins_and_closes_failed_child(self):
        import copy
        from unittest.mock import patch,Mock
        from simulator.fleet_care import FleetCareWorld,FleetCareRuntime
        from simulator.treatment_runtime import TreatmentRuntime
        from simulator.fleet_continuation import continue_fleet
        parent=FleetCareWorld();parent.status='paused'
        worker=OrchardCare(parent.seed,1,'W1',parent.tasks[0]);worker.status='paused'
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
            self.assertTrue(child.provider_routes['W1']['fallback'])
        finally:runtime.close()
        created=[]
        original=FleetCareRuntime.make_child
        def track(runtime,*args):
            child=original(runtime,*args);created.append(child);return child
        with patch('threading.Thread.start'),patch.object(FleetCareRuntime,'make_child',track),patch.object(TreatmentRuntime,'persist',return_value=False):
            with self.assertRaisesRegex(ValueError,'checkpoint'):continue_fleet(repo,parent.id,'test')
        self.assertEqual(len(created),1);self.assertTrue(created[0].closed)
