import math
import unittest
from simulator.treatment import Treatment
from simulator.care import PlantCare
from simulator.manipulation import Manipulation
from simulator.arm import fk,ik
from simulator.camera import project_pixel,project_ground
from simulator.common import uid
from simulator import lidar


def frame(w):
    r=w.request_frame(); return w.accept_frame(r['id'],{'id':uid(),'ready':True})
def command(w,action,**args):
    result=w.command(uid(),'T1',action,**args)
    if not result['accepted']: raise AssertionError(result)
    while w.robot['action'] and w.status=='running': w.tick(.05)
    return result

def water(w):
    command(w,'approach'); frame(w); command(w,'read_moisture')
    uv=project_pixel(w.camera(),[.5,.08,0]); command(w,'aim_nozzle',u=uv[0],v=uv[1],frame_id=w.frame['id'])
    for amount in [5,5,5,5,1]:
        command(w,'dispense',liters=amount,frame_id=w.frame['id']); frame(w); command(w,'read_moisture')
    command(w,'read_flow')

class TreatmentTests(unittest.TestCase):
    def test_irrigation_complete_and_clog(self):
        w=Treatment();w.status='running';water(w);command(w,'return');frame(w);command(w,'verify');self.assertEqual(w.status,'completed')
        w=Treatment();w.status='running';command(w,'approach');frame(w);command(w,'read_moisture');uv=project_pixel(w.camera(),[.5,.08,0]);command(w,'aim_nozzle',u=uv[0],v=uv[1],frame_id=w.frame['id']);w.faults['nozzle']=True
        command(w,'dispense',liters=5,frame_id=w.frame['id']);self.assertEqual(w.effective,0);self.assertEqual(w.robot['water'],30)
        command(w,'service_tool');self.assertFalse(w.command(uid(),'T1','dispense',liters=1,frame_id=w.frame['id'])['accepted'])

    def test_care_and_restart(self):
        for seed in (0,8,31):
            w=PlantCare(seed);w.status='running';water(w);command(w,'next_stage');command(w,'select_tool',tool='gripper');frame(w)
            for weed in w.weeds:
                uv=project_pixel(w.camera(),weed['position']);command(w,'remove_weed',u=uv[0],v=uv[1],frame_id=w.frame['id']);frame(w)
            command(w,'next_stage');command(w,'select_tool',tool='fertilizer');frame(w);command(w,'read_prescription')
            command(w,'fertilize',grams=5,frame_id=w.frame['id']);w=PlantCare.restore(w.checkpoint());frame(w);command(w,'read_application')
            self.assertFalse(w.command(uid(),'T1','fertilize',grams=50,frame_id=w.frame['id'])['accepted'])
            while w.fertilizer_effective<w.prescription-1e-6:
                command(w,'fertilize',grams=min(5,w.prescription-w.fertilizer_effective),frame_id=w.frame['id']);frame(w);command(w,'read_application')
            command(w,'next_stage');command(w,'select_tool',tool='vacuum');frame(w)
            for pest in w.pests:
                uv=project_pixel(w.camera(),pest['position']);command(w,'remove_pest',u=uv[0],v=uv[1],frame_id=w.frame['id']);frame(w)
            command(w,'next_stage');command(w,'return');frame(w);command(w,'verify');self.assertTrue(all(w.verify().values()),w.verify())
            self.assertEqual(len(w.verify()),11)

    def test_bad_aim_stale_and_false_clearance(self):
        w=PlantCare();w.status='running';self.assertFalse(all(w.verify().values()))
        frame(w);w.invalidate();self.assertFalse(w.command(uid(),'T1','aim_nozzle',u=.5,v=.8,frame_id=w.frame['id'])['accepted'])
        w.prescription=0;self.assertFalse(w.verify()['inventory'])

class ArmTests(unittest.TestCase):
    def test_fk_ik_and_calibration(self):
        for seed in (7,8,31):
            w=Manipulation(seed)
            for p in ([0,.8,2.2,0,0,0],[w.weed['position'][0],.15,w.weed['position'][2],0,0,0],[.95,.9,2.5,10,20,25]):
                actual=fk(ik(p,w.base()),w.base())
                self.assertLess(sum((a-b)**2 for a,b in zip(actual['position'],p[:3])),1e-12)
            before=w.camera();w.weed['position'][0]+=1;self.assertEqual(w.camera(),before)

    def test_whole_slip_extract_restore_deposit(self):
        w=Manipulation(7,'known');w.status='running';frame(w)
        x,_,z=w.weed['position'];command(w,'move_arm',pose=[x,.15,z,0,0,0]);frame(w)
        command(w,'set_gripper',opening=.02,force=12);self.assertTrue(w.holding)
        command(w,'move_arm',pose=[x,.4,z,0,0,0]);self.assertFalse(w.holding);self.assertFalse(w.extracted)
        command(w,'open_gripper');command(w,'move_arm',pose=[x,.15,z,0,0,0]);frame(w);command(w,'set_gripper',opening=.02,force=30)
        command(w,'move_arm',pose=[x,.5,z,0,0,0]);self.assertTrue(w.extracted);self.assertTrue(w.holding)
        w=Manipulation.restore(w.checkpoint());command(w,'move_arm',pose=[.95,.9,2.5,0,0,0]);command(w,'open_gripper');self.assertTrue(w.deposited)
        frame(w);command(w,'return');command(w,'verify');self.assertTrue(all(w.verify().values()),w.verify())

    def test_staged_false_claim_and_atomic_scan(self):
        w=Manipulation(7,'wrist');w.status='running';frame(w)
        self.assertFalse(w.command(uid(),'T1','move_arm',pose=[0,.5,2,0,0,0])['accepted'])
        command(w,'assess_alignment',frame_id=w.frame['id'],stem_between_fingers=True,depth_consistent=True,evidence='Both fingers appear centered')
        command(w,'set_gripper',opening=.02,force=30);self.assertFalse(w.holding);frame(w)
        self.assertFalse(w.command(uid(),'T1','confirm_contact',frame_id=w.frame['id'],evidence='I claim to have contact')['accepted'])
        req=lidar.request(w.frame,.5,.5);self.assertEqual(len(req['rays']),169)
        with self.assertRaises(ValueError):lidar.validate(req,req['id'],w.frame['id'],w.revision,[[.5,.5,0,0,0]]*169)

    def test_full_staged_mission_with_force_adjustment(self):
        from simulator.camera import ray,add,scale
        for trial in ('alignment','wrist'):
            w=Manipulation(7,trial);w.status='running';frame(w)
            command(w,'scan_lidar',u=.5,v=.5,span=.24,frame_id=w.frame['id'])
            req=w.depth_request
            points=[uv+add(req['camera']['position'],scale(ray(req['camera'],*uv),1.0)) for uv in req['rays']]
            w.accept_depth(req['id'],req['frame_id'],req['revision'],points,{'id':uid(),'ready':True})
            self.assertTrue(w.nonempty_scan)
            x,_,z=w.weed['position']
            def assess():
                frame(w);command(w,'assess_alignment',frame_id=w.frame['id'],stem_between_fingers=True,depth_consistent=True,evidence='Scripted geometry fixture: stem lies between both fingers')
            def acknowledge():
                frame(w);command(w,'confirm_contact',frame_id=w.frame['id'],evidence='Measured holding and positive load are present')
            command(w,'move_arm',pose=[x,.15,z,0,0,0]);assess();command(w,'set_gripper',opening=.02,force=12)
            acknowledge();command(w,'move_arm',pose=[x,.4,z,0,0,0]);self.assertFalse(w.holding)
            command(w,'open_gripper');command(w,'move_arm',pose=[x,.15,z,0,0,0]);assess();command(w,'set_gripper',opening=.02,force=12)
            acknowledge();command(w,'set_gripper',opening=.02,force=30)
            self.assertFalse(w.command(uid(),'T1','move_arm',pose=[x,.5,z,0,0,0])['accepted'])
            acknowledge();command(w,'move_arm',pose=[x,.5,z,0,0,0]);self.assertTrue(w.extracted)
            w=Manipulation.restore(w.checkpoint());command(w,'move_arm',pose=[.95,.9,2.5,0,0,0]);command(w,'open_gripper');frame(w)
            command(w,'return');command(w,'verify');self.assertTrue(all(w.verify().values()),w.verify())
