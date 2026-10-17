import os
import unittest
from simulator.common import load_env,uid
from simulator.engine import Mission
from simulator.persistence import Repository,StorageError

@unittest.skipUnless(os.getenv('WALLNE_INTEGRATION')=='1','requires explicitly selected Supabase test project')
class PersistenceIntegration(unittest.TestCase):
    def test_atomic_retry_fencing_and_private_read(self):
        load_env();repo=Repository();w=Mission(rows=0);lease=repo.create(w,dict(mode='test',test_only=True));batch=repo.batch(w,0,[],[])
        first=repo.commit(batch);self.assertEqual(first,repo.commit(batch));self.assertEqual(repo.restore(w.id)['id'],w.id)
        other=Repository()
        with self.assertRaises(StorageError):other.lease(w.id)
        w.event('test_boundary');bad=repo.batch(w,first['sequence'],[],[]);bad['events'][0]['sequence']+=3
        with self.assertRaises(StorageError):repo.commit(bad)
        self.assertEqual(repo.read('sessions',f'id=eq.{w.id}&limit=1')[0]['committed_sequence'],first['sequence'])
        repo.lease(w.id)
        self.assertEqual(repo.commit(repo.batch(w,first['sequence'],[],[]))['sequence'],w.seq)
        if os.getenv('SUPABASE_PUBLISHABLE_KEY'):
            public=Repository(key=os.environ['SUPABASE_PUBLISHABLE_KEY'])
            try:rows=public.read('checkpoints',f'session_id=eq.{w.id}&limit=1');self.assertEqual(rows,[])
            except StorageError:pass
