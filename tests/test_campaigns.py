import types
import unittest
from unittest.mock import Mock,patch
from simulator.evaluation import Campaigns


class CampaignTests(unittest.TestCase):
    def campaign(self):
        return dict(id='test',baseline_id='baseline',candidate_id='candidate',results=[],status='running',manifest=dict(scenarios=['seed7'],seeds=[7],engine='gemini',trial='wrist',models={},provider_base='test',code_hash='frozen'))

    def test_storage_interruption_preserves_pending_child_and_finalizes(self):
        runtime=Mock(config={'code_hash':'frozen'},storage_error='transport unavailable',world=types.SimpleNamespace(status='running'))
        runtime.snapshot.return_value=dict(id='child',checks={'preserved':True,'inventory':True,'battery':True},status='storage_blocked',decisions=2,inference={'cost':.1})
        app=Mock(treatment=runtime);app.reset.return_value={'id':'child'}
        service=Campaigns(app);campaign=self.campaign()
        with patch.object(service,'finalize') as finalize:service.run(campaign)
        runtime.pause.assert_not_called();finalize.assert_called_once()
        self.assertFalse(campaign['passed']);self.assertEqual(campaign['results'][0]['session_id'],'child')

    def test_changed_implementation_retains_rejected_child(self):
        runtime=Mock(config={'code_hash':'changed'},storage_error=None,world=types.SimpleNamespace(status='paused'))
        app=Mock(treatment=runtime);app.reset.return_value={'id':'child'}
        service=Campaigns(app);campaign=self.campaign()
        with patch.object(service,'finalize'):service.run(campaign)
        runtime.start.assert_not_called();self.assertFalse(campaign['passed'])
        self.assertEqual(campaign['results'][0]['session_id'],'child')
        self.assertEqual(campaign['results'][0]['status'],'blocked')
