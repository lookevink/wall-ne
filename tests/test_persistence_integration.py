import os
import unittest
from simulator.common import load_env,uid
from simulator.engine import Mission
from simulator.persistence import Repository,StorageError

@unittest.skipUnless(os.getenv('WALLNE_INTEGRATION')=='1','requires explicitly selected Supabase test project')
class PersistenceIntegration(unittest.TestCase):
    def test_atomic_retry_fencing_and_private_read(self):
        load_env();repo=Repository();self.addCleanup(repo.close_current);w=Mission(rows=0);lease=repo.create(w,dict(mode='test',test_only=True));batch=repo.batch(w,0,[],[])
        first=repo.commit(batch);self.assertEqual(first,repo.commit(batch));self.assertEqual(repo.restore(w.id)['id'],w.id)
        other=Repository();self.addCleanup(other.close_current)
        with self.assertRaises(StorageError):other.lease(w.id)
        w.event('test_boundary');bad=repo.batch(w,first['sequence'],[],[]);bad['events'][0]['sequence']+=3
        with self.assertRaises(StorageError):repo.commit(bad)
        self.assertEqual(repo.read('sessions',f'id=eq.{w.id}&limit=1')[0]['committed_sequence'],first['sequence'])
        repo.lease(w.id)
        self.assertEqual(repo.commit(repo.batch(w,first['sequence'],[],[]))['sequence'],w.seq)
        if os.getenv('SUPABASE_PUBLISHABLE_KEY'):
            public=Repository(key=os.environ['SUPABASE_PUBLISHABLE_KEY']);self.addCleanup(public.close_current)
            try:rows=public.read('checkpoints',f'session_id=eq.{w.id}&limit=1');self.assertEqual(rows,[])
            except StorageError:pass

    def test_outage_freezes_partial_work_and_retries_same_batch(self):
        from unittest.mock import patch
        from simulator.runtime import Runtime
        from simulator.agents import DemoController
        from simulator.common import canonical
        load_env();world=Mission(8);world.status='running';controller=DemoController()
        for _ in range(2000):
            controller.step(world);world.tick(.25)
            if any(0<z['delivered']<5 for z in world.zones.values()):break
        with patch('threading.Thread.start'):
            runtime=Runtime(world=world,repository=Repository())
        self.assertTrue(runtime.persist());boundary=runtime.repository.restore(world.id)
        world.tick(.25);world.event('test_partial_progress');progress=world.checkpoint()
        actual_commit=runtime.repository.commit
        with patch.object(runtime.repository,'commit',side_effect=StorageError('injected transport outage')):
            self.assertFalse(runtime.persist());batch_id=runtime.pending['batch_id']
            frozen=world.checkpoint();runtime.step(1);self.assertEqual(world.checkpoint(),frozen)
            self.assertEqual(runtime.repository.restore(world.id)['zones'],boundary['zones'])
        runtime.retry();self.assertIsNone(runtime.pending);self.assertEqual(world.status,'paused')
        saved=runtime.repository.restore(world.id);self.assertEqual(saved['zones'],progress['zones'])
        self.assertTrue(runtime.committed>boundary['seq']);runtime.close()

    def test_arm_checkpoint_numeric_hash_roundtrip(self):
        from simulator.manipulation import Manipulation
        load_env();repo=Repository();self.addCleanup(repo.close_current)
        world=Manipulation(7,'wrist');repo.create(world,dict(mode='test',test_only=True))
        repo.commit(repo.batch(world,0,[],[]))
        restored=repo.restore(world.id)
        self.assertEqual(restored['joints'],world.joints)
        self.assertTrue(repo.checkpoint_record(world.id)[1])

    def test_prompt_gate_immutability_and_rollback_isolated_role(self):
        from simulator.common import digest
        load_env();repo=Repository();self.addCleanup(repo.close_current)
        role='integration-test-'+uid();baseline=uid();candidate=uid()
        for ident,parent in ((baseline,None),(candidate,baseline)):
            text='Synthetic gate fixture; never used by an execution role.'
            repo.request('POST','/rest/v1/prompt_versions',dict(id=ident,role=role,text=text,hash=digest(text),parent_id=parent,status='candidate'))
        def evaluation(passed):
            ident=uid()
            repo.request('POST','/rest/v1/evaluations',dict(id=ident,baseline_id=baseline,candidate_id=candidate,manifest={'test_only':True},results=[],passed=passed,reason='Synthetic database gate integration test'))
            return ident
        failed=evaluation(False)
        with self.assertRaises(StorageError):repo.rpc('wallne_activate',dict(p_version=candidate,p_evaluation=failed))
        self.assertEqual(repo.read('prompt_versions',f'id=eq.{candidate}')[0]['status'],'candidate')
        passed=evaluation(True)
        repo.rpc('wallne_activate',dict(p_version=baseline,p_evaluation=passed,p_rollback=True))
        original=Mission(rows=0);original.prompt_versions={role:'unset'}
        repo.create(original,dict(mode='test',test_only=True))
        repo.rpc('wallne_activate',dict(p_version=candidate,p_evaluation=passed))
        subsequent=Mission(rows=0);subsequent.prompt_versions={role:'unset'}
        repo.create(subsequent,dict(mode='test',test_only=True))
        self.assertEqual(original.prompt_versions[role],baseline)
        self.assertEqual(subsequent.prompt_versions[role],candidate)
        with self.assertRaises(StorageError):repo.request('PATCH',f'/rest/v1/prompt_versions?id=eq.{candidate}',dict(text='Alter immutable text'))
        with self.assertRaises(StorageError):repo.request('PATCH',f'/rest/v1/evaluations?id=eq.{failed}',dict(passed=True))
        repo.rpc('wallne_activate',dict(p_version=baseline,p_evaluation=passed,p_rollback=True))
        self.assertEqual(repo.read('prompt_versions',f'id=eq.{baseline}')[0]['status'],'active')
        self.assertEqual(repo.read('prompt_versions',f'id=eq.{candidate}')[0]['status'],'retired')
        self.assertEqual(len(repo.read('prompt_activations',f'role=eq.{role}')),3)
        self.assertEqual(repo.read('sessions',f'id=eq.{original.id}')[0]['metadata']['prompt_versions'][role],baseline)
