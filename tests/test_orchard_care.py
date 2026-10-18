import unittest
from simulator.orchard_care import OrchardCare
from simulator.camera import project_pixel as project
from tests.test_treatment import frame,command


class OrchardCareTests(unittest.TestCase):
    def test_every_parking_station_clears_chassis_and_carried_arm(self):
        from simulator.orchard_care import care_station
        from simulator.orchard_manipulation import TREES
        from simulator.arm import ik,trajectory
        import math
        trunks=[[t['position'][0],t['position'][2]] for t in TREES]
        for tree in TREES:
            x,z=care_station(tree);base=[x,.8,z-.5]
            self.assertTrue(all(math.hypot(x-tx,z-tz)>=.85 for tx,tz in trunks))
            joints=ik([x,.8,z-1.6,0,0,0],base)
            trajectory(joints,joints,base,trunks)

    def test_interior_navigation_arrives_with_clear_arm(self):
        from simulator.fleet_care import FleetCareWorld
        from simulator.arm import trajectory
        w=OrchardCare(7,1,'W1',FleetCareWorld(tree_count=169).tasks[13])
        w.status='running';w.begin();self.settle(w)
        self.assertEqual(w.phase,'inspection')
        trajectory(w.joints,w.joints,w.base(),w.trunks)

    def settle(self,w):
        for _ in range(12000):
            if not w.robot['action']:return
            w.tick(.05)
            if w.status!='running':self.fail(w.feedback)
        self.fail('motion did not settle')

    def act(self,w,action,**args):
        if not w.frame or w.frame['revision']!=w.revision or w.frame['phase']!=w.phase:frame(w)
        receipt=w.command(str(w.decisions), 'W1',action,frame_id=w.frame['id'],**args)
        self.assertTrue(receipt['accepted'],receipt)
        self.settle(w)

    def test_ten_tree_mission_and_restore(self):
        w=OrchardCare();w.status='running';w.begin();self.settle(w)
        for i in range(10):
            self.assertEqual(w.task_index,i);self.assertEqual(w.phase,'inspection')
            self.assertFalse(w.verify()['trees_complete'])
            self.act(w,'inspect_tree')
            x,_,z=w.orchard['tree']['position']
            u,v=project(w.camera(),[x,.08,z+.35])
            self.act(w,'aim_nozzle',u=u,v=v);self.act(w,'water_tree');self.act(w,'read_moisture');self.act(w,'next_stage')
            self.assertAlmostEqual(w.robot['water'],9)
            self.act(w,'fertilize_tree');self.act(w,'read_application');self.act(w,'next_stage')
            for p in w.pests:
                u,v=project(w.camera(),p['position']);self.act(w,'remove_pest',u=u,v=v)
            self.act(w,'next_stage');self.assertEqual(w.phase,'extraction')
            w.nonempty_scan=True;x,_,z=w.weed['position']
            self.act(w,'move_arm',pose=[x,.4,z,0,0,0]);self.act(w,'move_arm',pose=[x,.13,z,0,0,0])
            u,v=project(w.camera(),[x,.08,z]);self.act(w,'project_ground',u=u,v=v)
            self.act(w,'assess_alignment',stem_between_fingers=True,depth_consistent=True,evidence='Test fixture aligns central stem between finger faces')
            self.act(w,'set_gripper',opening=0,force=30)
            self.act(w,'confirm_contact',evidence='Measured contact and positive load')
            self.act(w,'move_arm',pose=[x,.33,z,0,0,0]);self.act(w,'move_arm',pose=[w.bin[0],.8,w.bin[2],0,0,0]);self.act(w,'open_gripper')
            self.act(w,'verify')
            self.assertEqual(len(w.completed_trees),i+1)
            w=OrchardCare.restore(w.checkpoint())
        self.assertEqual(w.phase,'final');self.assertEqual(w.status,'running')
        self.act(w,'verify');self.assertEqual(w.status,'completed');self.assertTrue(all(w.verify().values()),w.verify())
        self.assertEqual(len(w.service_log),10);self.assertEqual(w.unloaded_total,10)
        self.assertGreater(w.robot['minimum_battery'],25)

    def test_no_hidden_targets_and_no_false_clearance(self):
        w=OrchardCare();w.status='running';w.begin();self.settle(w);frame(w)
        obs=w.observations()
        for name in ('tasks','weed','pests','beneficial','protected'):self.assertNotIn(name,obs)
        self.assertFalse(w.command('bad','W1','next_stage',frame_id=w.frame['id'])['accepted'])
        self.act(w,'inspect_tree');self.act(w,'aim_nozzle',u=.7,v=.8)
        frame(w);self.assertFalse(w.command('outside','W1','water_tree',frame_id=w.frame['id'])['accepted'])
        self.assertEqual(w.robot['water'],30)
        self.assertFalse(w.command('bad2','W1','next_stage',frame_id=w.frame['id'])['accepted'])
        self.assertFalse(w.verify()['watered'])

    def test_frames_from_another_tree_cannot_verify_extraction(self):
        w=OrchardCare();w.frames=[dict(task_index=99,extracted=False),dict(task_index=99,deposited=True)]
        self.assertFalse(w.task_checks()['images'])
        w.tasks[0]['prescription']=100
        self.assertFalse(w.verify()['inventory'])

    def test_care_stage_cannot_loop_on_images_or_fresh_meters(self):
        w=OrchardCare();w.status='running';w.begin();self.settle(w)
        self.assertNotIn('capture_image',w.allowed_actions())
        self.act(w,'inspect_tree');self.assertNotIn('read_moisture',w.allowed_actions())
        x,_,z=w.orchard['tree']['position'];u,v=project(w.camera(),[x,.08,z+.35])
        self.act(w,'aim_nozzle',u=u,v=v);self.act(w,'water_tree')
        self.assertEqual(w.allowed_actions(),['stop','read_moisture'])
        self.act(w,'read_moisture');self.assertEqual(w.allowed_actions(),['stop','next_stage'])
        self.act(w,'next_stage');self.act(w,'fertilize_tree')
        self.assertEqual(w.allowed_actions(),['stop','read_application'])
        self.act(w,'read_application');self.assertEqual(w.allowed_actions(),['stop','next_stage'])
        self.act(w,'next_stage');self.assertEqual(set(w.allowed_actions()),{'stop','remove_pest','next_stage'})

    def test_approach_pose_requires_descent_and_rejects_noop(self):
        w=OrchardCare();w.status='running';w.begin();self.settle(w);w.phase='extraction';w.nonempty_scan=True
        x,_,z=w.weed['position'];self.act(w,'move_arm',pose=[x,.4,z,0,0,0])
        self.assertNotIn('assess_alignment',w.allowed_actions())
        self.assertIn('project_ground',w.observations()['current_grasp_step']['next_action'])
        before=w.robot['position'][:];frame(w)
        r=w.command('no-op','W1','move_arm',pose=[x,.4,z,0,0,0])
        self.assertFalse(r['accepted']);self.assertIn('already at this pose',r['reason']);self.assertIsNone(w.robot['action'])
        self.act(w,'move_arm',pose=[x,.13,z,0,0,0]);self.assertNotIn('assess_alignment',w.allowed_actions())
        u,v=project(w.camera(),[x,.08,z]);self.act(w,'project_ground',u=u,v=v);self.assertIn('assess_alignment',w.allowed_actions())

    def test_crown_projection_uses_camera_ray_not_hidden_target(self):
        w=OrchardCare();w.status='running';w.begin();self.settle(w);w.phase='extraction';w.nonempty_scan=True
        x,_,z=w.orchard['tree']['position'];selected=[x+.2,.08,z+1.4]
        u,v=project(w.camera(),selected);self.act(w,'project_ground',u=u,v=v)
        measured=w.observations()['crown_projection']
        for axis,value in zip(('x','y','z'),selected):self.assertAlmostEqual(measured['world'][axis],value)
        self.assertEqual(measured['grasp_tool_center_y'],.13)
        original=measured['world'].copy();w.weed['position']=[99,.08,99]
        self.act(w,'project_ground',u=u,v=v);self.assertEqual(w.crown_projection['world'],original)
