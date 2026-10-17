import copy
import unittest
from unittest.mock import patch
from simulator.engine import Mission
from simulator.treatment import Treatment
from simulator.runtime import Runtime
from simulator.treatment_runtime import TreatmentRuntime
from simulator.telemetry import Telemetry
from simulator.common import uid

class SavedRepository:
    def __init__(self,w,config):
        self.state=w.checkpoint();self.config=config;self.kind=w.kind;self.sequence=w.seq
    def read(self,table,query):
        if table=='sessions':return [dict(kind=self.kind,metadata={'configuration':self.config})]
        return []
    def restore(self,session):return copy.deepcopy(self.state)
    def lease(self,session):return {'sequence':self.sequence,'resume_epoch':2}

class RecoveryTests(unittest.TestCase):
    def test_frozen_live_configuration_survives_restore(self):
        w=Mission();w.runtime_state=dict(inference=[{'cost':.12}],failures={'W1':1},active_wall=20)
        repo=SavedRepository(w,dict(mode='live',engine='gemini',speed=4))
        with patch('threading.Thread.start'),patch.object(Runtime,'persist',return_value=True):
            runtime=Runtime(repository=repo);runtime.restore(w.id)
            self.assertEqual(runtime.config,repo.config);self.assertEqual(runtime.inference,[{'cost':.12}]);self.assertEqual(runtime.active_wall,20);runtime.close()

    def test_restore_requires_new_pixels_and_matching_family(self):
        w=Treatment();r=w.request_frame();w.accept_frame(r['id'],{'id':uid(),'ready':True})
        repo=SavedRepository(w,dict(mode='vision',engine='gemini',speed=4))
        with patch('threading.Thread.start'),patch.object(Runtime,'persist',return_value=True):
            runtime=TreatmentRuntime(repository=repo);runtime.image='old image';runtime.pixels=b'old';runtime.restore(w.id)
            self.assertIsNone(runtime.image);self.assertIsNone(runtime.pixels);self.assertIsNone(runtime.world.frame);self.assertEqual(len(runtime.world.frames),1);runtime.close()
            fleet=Runtime(repository=repo)
            with self.assertRaises(ValueError):fleet.restore(w.id)
            fleet.close()

    def test_motion_sample_is_not_mutable_live_state(self):
        w=Treatment();t=Telemetry();t.sample(w,1);w.robot['position'][1]=7
        self.assertEqual(t.motion[0]['position'],[0,8]);self.assertEqual(t.latest['T1']['position'],[0,8])
