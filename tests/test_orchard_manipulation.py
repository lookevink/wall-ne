import unittest
from unittest.mock import patch
from simulator.orchard_manipulation import OrchardManipulation
from simulator.treatment_runtime import TreatmentRuntime
from simulator.arm import ik,trajectory
from tests.test_treatment import frame,command

class OrchardManipulationTests(unittest.TestCase):
    def arrive(self,w):
        w.status='running';w.begin()
        for _ in range(1000):
            w.tick(.05)
            if not w.robot['action']:break
        self.assertEqual(w.phase,'extraction');self.assertEqual(w.robot['position'],w.station)

    def test_navigation_restore_and_world_coordinate_extraction(self):
        w=OrchardManipulation(7);w.status='running';w.begin();w.tick(.5)
        self.assertNotEqual(w.robot['position'],w.station)
        self.assertEqual(w.allowed_actions(),['stop'])
        w=OrchardManipulation.restore(w.checkpoint());self.arrive(w)
        self.assertLess(w.robot['battery'],100);self.assertEqual(w.robot['id'],'W1')
        self.assertNotIn('weed',w.observations());self.assertNotIn('diagnostic_known_grasp',w.observations())
        w.nonempty_scan=True;x,_,z=w.weed['position']
        command(w,'move_arm',pose=[x,.4,z,0,0,0]);command(w,'move_arm',pose=[x,.13,z,0,0,0]);frame(w)
        command(w,'assess_alignment',frame_id=w.frame['id'],stem_between_fingers=True,depth_consistent=True,evidence='Both finger faces bracket the observed central stem')
        command(w,'set_gripper',opening=0,force=30);frame(w)
        command(w,'confirm_contact',frame_id=w.frame['id'],evidence='Measured holding and positive load confirm contact')
        command(w,'move_arm',pose=[x,.33,z,0,0,0]);self.assertTrue(w.extracted)
        command(w,'move_arm',pose=[w.bin[0],.8,w.bin[2],0,0,0]);command(w,'open_gripper');frame(w);command(w,'verify')
        self.assertTrue(w.stage_verified);self.assertFalse(w.verify()['returned'])
        command(w,'return');frame(w);command(w,'verify')
        self.assertEqual(w.status,'completed');self.assertTrue(all(w.verify().values()))
        restored=OrchardManipulation.restore(w.checkpoint())
        self.assertTrue(restored.weed['removed']);self.assertTrue(restored.deposited)
        self.assertEqual(restored.robot['position'],restored.robot['home'])
        self.assertTrue(all(r['robot_id']=='W1' for r in restored.receipts.values()))

    def test_shifted_orchard_trunks_are_collision_checked(self):
        w=OrchardManipulation();self.arrive(w);x,z=w.trunks[90]
        joints=ik([x,.15,z,0,0,0],[x,.8,z+1.8])
        with self.assertRaisesRegex(ValueError,'trunk'):trajectory(joints,joints,[x,.8,z+1.8],w.trunks)

    def test_orchard_rejects_lab_sensor_submissions(self):
        with patch('threading.Thread.start'):
            runtime=TreatmentRuntime(OrchardManipulation(),config=dict(mode='vision',engine='crusoe'))
        for method in (runtime.accept_frame,runtime.accept_depth):
            with self.assertRaisesRegex(ValueError,'orchard sensor'):method(dict(arena='laboratory'))
        runtime.executor.shutdown(wait=False)
