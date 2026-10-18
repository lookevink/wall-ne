import tempfile
import threading
import unittest
from simulator.background_storage import BackgroundRepository,REGISTRY,REGISTRY_LOCK,ensure_cloud_restore_safe
from simulator.persistence import StorageError


class Remote:
    url='https://test.invalid';bucket='test';key='fake';writer='original-writer'
    def __init__(self):self.leases={};self.calls=[];self.commits={};self.uncertain=False
    def read(self,*args):return [dict(writer=self.writer,fence=3)]
    def lease(self,session):
        lease=dict(fence=3,resume_epoch=0,sequence=max((b['sequence'] for b in self.commits.values()),default=0));self.leases[session]=lease;return lease
    def artifact(self,session,robot,kind,raw,metadata):
        import hashlib
        sha=hashlib.sha256(raw).hexdigest();self.calls.append('artifact')
        return dict(sha256=sha,object_key=f'{session}/{kind}/{sha}.png')
    def commit(self,batch):
        self.calls.append('commit');self.commits.setdefault(batch['batch_id'],batch)
        if self.uncertain:self.uncertain=False;raise StorageError('uncertain acknowledgement')
        return dict(sequence=batch['sequence'])


class BackgroundStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.remote=Remote();self.repo=BackgroundRepository(self.remote,self.tmp.name,autostart=False)
        self.repo._open('test-outbox',dict(sequence=0,fence=3,resume_epoch=0))
        self.addCleanup(self.cleanup)

    def cleanup(self):
        with REGISTRY_LOCK:REGISTRY.pop('test-outbox',None)
        self.repo.db.close()

    def batch(self):return dict(session_id='test-outbox',batch_id='immutable-batch',writer=self.remote.writer,fence=3,expected_sequence=0,sequence=5,revision=2)

    def test_local_restart_uses_latest_integrity_checked_checkpoint_without_dropping_backlog(self):
        from simulator.background_storage import local_restart_checkpoint
        from simulator.common import digest,canonical
        from unittest.mock import Mock
        state=dict(id='test-outbox',seq=5,status='running',runtime_state={'pending_requests':{}})
        batch=dict(self.batch(),state=state,integrity_hash=digest(state));self.repo.commit(batch)
        cloud=Mock()
        self.assertEqual(local_restart_checkpoint(cloud,'test-outbox'),state)
        cloud.restore.assert_not_called();self.assertEqual(self.repo.status()['pending_operations'],1)
        batch['state']['seq']=4
        with self.repo.db:self.repo.db.execute('update queue set payload=?',(canonical(batch),))
        with self.assertRaisesRegex(StorageError,'integrity'):
            local_restart_checkpoint(cloud,'test-outbox')

    def test_network_wait_does_not_hold_enqueue_lock_and_artifact_precedes_commit(self):
        entered=threading.Event();release=threading.Event();original=self.remote.artifact
        def slow(*args):entered.set();release.wait(2);return original(*args)
        self.remote.artifact=slow
        artifact=self.repo.artifact('test-outbox','W1','frame',b'evidence',{})
        thread=threading.Thread(target=self.repo.drain_one);thread.start();entered.wait(1)
        try:
            self.repo.commit(self.batch())
            self.assertFalse(release.is_set())
            self.assertEqual(self.repo.status()['cloud_committed_sequence'],0)
            self.assertEqual(self.repo.status()['queued_sequence'],5)
            self.assertEqual(self.repo.local_artifact(artifact['id'])[0],b'evidence')
            with self.assertRaises(StorageError):ensure_cloud_restore_safe()
        finally:release.set();thread.join()
        self.assertTrue(self.repo.drain_one())
        self.assertEqual(self.remote.calls,['artifact','commit'])
        self.assertTrue(self.repo.status()['synced'])

    def test_uncertain_cloud_ack_replays_original_batch_after_local_restart(self):
        batch=self.batch();self.repo.commit(batch);batch['sequence']=99
        self.remote.uncertain=True
        with self.assertRaises(StorageError):self.repo.drain_one()
        self.repo.db.close()
        self.repo=BackgroundRepository(self.remote,self.tmp.name,autostart=False);self.repo._open('test-outbox')
        self.assertTrue(self.repo.drain_one())
        self.assertEqual(len(self.remote.commits),1)
        self.assertEqual(self.remote.commits['immutable-batch']['sequence'],5)
        self.assertEqual(self.remote.commits['immutable-batch']['writer'],'original-writer')
        self.assertEqual(self.remote.commits['immutable-batch']['fence'],3)
        self.assertTrue(self.repo.status()['synced'])

    def test_conflicting_writer_cannot_rewrite_queued_fence(self):
        self.repo.commit(self.batch());self.remote.read=lambda *args:[dict(writer='another-writer',fence=4)]
        with self.assertRaises(StorageError):self.repo.drain_one()
        self.assertEqual(self.repo.status()['pending_operations'],1)
        self.assertFalse(self.remote.commits)
        self.assertEqual(self.remote.leases['test-outbox']['fence'],3)

    def test_noncontiguous_batch_cannot_acknowledge_local_progress(self):
        batch=self.batch();batch['expected_sequence']=2
        with self.assertRaises(StorageError):self.repo.commit(batch)
        self.assertEqual(self.repo.status()['queued_sequence'],0)
        self.assertEqual(self.repo.status()['pending_operations'],0)

    def test_restore_reuses_existing_sender_after_sync(self):
        from simulator.background_storage import bind_for_restore
        self.repo.commit(self.batch());self.repo.drain_one()
        fresh=BackgroundRepository(Remote(),self.tmp.name,autostart=False)
        rebound=bind_for_restore(fresh,'test-outbox')
        self.assertIs(rebound,self.repo)
        self.assertEqual(rebound.lease('test-outbox')['sequence'],5)

    def test_incomplete_outbox_is_reported_without_stopping_other_recovery(self):
        import pathlib,sqlite3
        from simulator.background_storage import recover_outboxes,RECOVERY_ERRORS,sync_status
        db=sqlite3.connect(str(pathlib.Path(self.tmp.name)/'incomplete.sqlite'));db.close()
        self.addCleanup(lambda:RECOVERY_ERRORS.pop('incomplete',None))
        recover_outboxes(self.remote,self.tmp.name)
        self.assertIn('incomplete',sync_status()['recovery_errors'])
        with self.assertRaises(StorageError):ensure_cloud_restore_safe()
        self.assertTrue((pathlib.Path(self.tmp.name)/'incomplete.sqlite').exists())

    def test_fleet_restore_scope_ignores_only_its_new_batches_and_resets_guard(self):
        from simulator.background_storage import cloud_restore_scope
        with cloud_restore_scope():
            self.repo.commit(self.batch())
            ensure_cloud_restore_safe()  # A child restore in this same operation.
        with self.assertRaises(StorageError):ensure_cloud_restore_safe()
        with self.assertRaises(StorageError):
            with cloud_restore_scope():pass

    def test_restore_rebind_updates_drained_sequence_and_fence(self):
        from simulator.background_storage import bind_for_restore
        self.repo.commit(self.batch());self.repo.drain_one()
        self.remote.lease=lambda session:dict(fence=7,resume_epoch=4,sequence=12)
        rebound=bind_for_restore(self.repo,'test-outbox')
        self.assertEqual(rebound.status()['queued_sequence'],12)
        import json
        lease=json.loads(rebound.db.execute("select value from metadata where key='lease'").fetchone()[0])
        self.assertEqual(lease['fence'],7)

    def test_missing_local_artifact_is_distinct_from_corrupt_evidence(self):
        from simulator.background_storage import LocalArtifactMissing
        with self.assertRaises(LocalArtifactMissing):self.repo.local_artifact('missing')
        artifact=self.repo.artifact('test-outbox','W1','frame',b'original',{})
        with self.repo.db:self.repo.db.execute('update artifacts set bytes=? where id=?',(b'corrupt',artifact['id']))
        with self.assertRaises(StorageError):self.repo.local_artifact(artifact['id'])
