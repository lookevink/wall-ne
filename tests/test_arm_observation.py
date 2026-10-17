import struct
import unittest
import zlib
from simulator.manipulation import Manipulation
from simulator.arm import ik
from simulator.arm_observation import interpret_scan,progress_state
from simulator.png import crop_url,decode
from tests.test_treatment import frame,command

class ArmObservationTests(unittest.TestCase):
    def test_surface_height_is_not_a_grasp_pose(self):
        for height,contact in ((.08,False),(.30,False),(.15,True)):
            w=Manipulation(7,'baseline');w.status='running'
            x,_,z=w.weed['position'];w.joints=ik([x,height,z,0,0,0],w.base())
            command(w,'set_gripper',opening=.02,force=30)
            self.assertEqual(w.holding,contact)
            if contact:
                command(w,'move_arm',pose=[x,.4,z,0,0,0]);self.assertTrue(w.extracted)
            else:self.assertIn('Tool center y=',w.feedback)
        obs=w.observations();self.assertEqual(obs['grasp_geometry']['grasp']['suggested_center_height_m'],.15)
        self.assertNotIn('diagnostic_known_grasp',obs)

    def test_scan_masks_only_known_geometry_and_ground(self):
        w=Manipulation();pose=w.tool_pose();points=[[.1,.1,4,-.01,4],[.2,.2,*pose['points'][0]],[.3,.3,.3,.2,1.4],None]
        info=interpret_scan(points,w.camera(),pose,w.opening,w.robot['position'])
        self.assertEqual(info['columns'],['u','v','world_x','world_y','world_z'])
        self.assertEqual(info['surface_classes'],['ground_plane','robot_geometry','unclassified_surface','no_return'])
        self.assertEqual(info['candidate_indices'],[2]);self.assertIsNone(info['range_m'][-1])
        # Same public sensor/robot state yields identical labels regardless of hidden inventory.
        w.weed['position']=[9,.08,9]
        self.assertEqual(info,interpret_scan(points,w.camera(),pose,w.opening,w.robot['position']))

    def test_capture_and_identical_move_loop_requires_changed_recovery(self):
        w=Manipulation();w.status='running';w.nonempty_scan=True;initial=w.tool_pose()['position']
        for _ in range(5):progress_state(w,'capture_image')
        self.assertTrue(w.control_progress['recovery_required'])
        for action,args in [('capture_image',{}),('move_arm',{'joints':w.joints[:]})]:
            self.assertFalse(w.command('repeat-'+action,'T1',action,**args)['accepted'])
        command(w,'move_arm',pose=[initial[0]+.06,initial[1],initial[2],0,0,0]);progress_state(w,'motion_completed')
        self.assertFalse(w.control_progress['recovery_required'])
        # A return to a previously visited pose is not novel progress.
        command(w,'move_arm',pose=initial+[0,0,0]);progress_state(w,'motion_completed')
        self.assertEqual(w.control_progress['stagnant_actions'],0)
        restored=Manipulation.restore(w.checkpoint());self.assertEqual(w.control_progress,restored.control_progress)

    def test_independent_contact_still_rejects_confident_bad_alignment(self):
        w=Manipulation();w.status='running';w.nonempty_scan=True;frame(w)
        command(w,'assess_alignment',frame_id=w.frame['id'],stem_between_fingers=True,depth_consistent=True,evidence='Both fingers appear aligned in this claimed view')
        command(w,'set_gripper',opening=.02,force=30)
        self.assertFalse(w.holding);self.assertEqual(w.load,0);self.assertFalse(w.extracted)

    def test_crop_is_exact_source_pixels_with_explicit_coordinate_mapping(self):
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        pixels=bytearray()
        for y in range(360):
            pixels.append(0)
            for x in range(640):pixels.extend([x%256,y%256,17,255])
        raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',640,360,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')
        crop,meta=crop_url(raw,[.25,.25,.5,.75]);_,_,rgb=decode(crop)
        self.assertEqual(meta['source_pixel_bounds'],[160,90,320,270])
        self.assertEqual(list(rgb[:4]),[160,90,17,255]);self.assertEqual(list(rgb[-4:]),[319%256,269%256,17,255])

    def test_complete_slip_regrasp_with_progress_accounting(self):
        w=Manipulation();w.status='running';w.nonempty_scan=True;x,_,z=w.weed['position']
        def run(action,**args):
            command(w,action,**args);w.record_control_progress('motion_completed' if action in ('move_arm','return') else action)
        def align():
            frame(w);run('assess_alignment',frame_id=w.frame['id'],stem_between_fingers=True,depth_consistent=True,evidence='Fresh image shows central stem between open jaws')
        def confirm():
            frame(w);run('confirm_contact',frame_id=w.frame['id'],evidence='Holding true with positive measured load')
        run('move_arm',pose=[x,.15,z,0,0,0]);align();run('set_gripper',opening=.02,force=12);confirm()
        run('move_arm',pose=[x,.5,z,0,0,0]);self.assertTrue(w.must_reopen)
        run('open_gripper');run('move_arm',pose=[x,.15,z,0,0,0]);align();run('set_gripper',opening=.02,force=30);confirm()
        run('move_arm',pose=[x,.5,z,0,0,0]);self.assertTrue(w.extracted)
        run('move_arm',pose=[.95,.9,2.5,0,0,0]);run('open_gripper');frame(w);run('return');run('verify')
        self.assertTrue(all(w.verify().values()));self.assertEqual(w.status,'completed')
