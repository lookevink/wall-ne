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
