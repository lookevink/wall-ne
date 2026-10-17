import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from scripts.arm_experiments import trial

class ExperimentTests(unittest.TestCase):
    def test_caps_stop_running_trial_and_export_failure_keeps_identity(self):
        import os
        state=dict(id='test-session',status='running',inference={'cost':1.1,'calls':2},checks={'extracted':False})
        calls=[]
        def api(path,body=None):
            calls.append(path)
            if path.endswith('/export'):raise OSError('export offline')
            if path.endswith('/stop'):state['status']='aborted'
            return state.copy()
        old=os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch('scripts.arm_experiments.api',api): result=trial('gemini','wrist')
            finally:os.chdir(old)
        self.assertIn('/api/treatment/stop',calls);self.assertEqual(result['session_id'],'test-session');self.assertEqual(result['status'],'aborted');self.assertIsNotNone(result['export_error'])

    def test_interruption_stops_outstanding_trial(self):
        state=dict(id='test-session',status='running',inference={'cost':None,'calls':0},checks={});reads=0;stopped=[]
        def api(path,body=None):
            nonlocal reads
            if path.endswith('/state'):
                reads+=1
                if reads==1:raise KeyboardInterrupt()
            if path.endswith('/stop'):stopped.append(True)
            return state
        with patch('scripts.arm_experiments.api',api):
            with self.assertRaises(KeyboardInterrupt):trial('gemini','wrist')
        self.assertEqual(stopped,[True])
