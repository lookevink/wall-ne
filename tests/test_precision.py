import json
import unittest
from unittest.mock import patch
from simulator.manipulation import Manipulation
from simulator.inference import Adapter,parse_response,InferenceError
from tests.test_treatment import frame,command

class PrecisionTests(unittest.TestCase):
    def test_restore_rejects_unsupported_profile_without_changing_valid_profiles(self):
        w=Manipulation(7,'precision');state=w.checkpoint()
        restored=Manipulation.restore(state)
        self.assertEqual(restored.camera(),w.camera())
        self.assertEqual(restored.allowed_actions(),w.allowed_actions())
        state['trial']='retired-profile'
        with self.assertRaisesRegex(ValueError,'unsupported'):Manipulation.restore(state)

    def test_filtered_scan_retains_evidence_and_named_coordinates(self):
        w=Manipulation(7,'precision')
        w.scan=dict(artifact_id='scan-evidence',frame_id='frame-evidence',revision=0,bounds=[0,0,1,1],rays=2,misses=0,points=[[.1,.2,.3,.4,.5],[.6,.7,.8,-.01,.9]],surface_classes=['unclassified_surface','ground_plane'])
        scan=w.observations()['scan']
        self.assertEqual(scan['artifact_id'],'scan-evidence')
        self.assertEqual(scan['returns'],[dict(image=dict(u=.1,v=.2),world=dict(x=.3,y=.4,z=.5))])

    def test_flat_schema_is_stage_gated_and_decodes_cartesian_pose(self):
        w=Manipulation(7,'precision');w.status='running';frame(w)
        self.assertEqual(w.allowed_actions(),['scan_lidar','capture_image','stop'])
        response={'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'treatment_action','arguments':json.dumps(dict(action='move_arm',reason='Approach stem',x=.1,y=.4,z=1.5,rx=0,ry=0,rz=0))}}]}}]}
        with self.assertRaises(InferenceError):parse_response(response,'treatment_action',w.allowed_actions())
        w.nonempty_scan=True
        parsed=parse_response(response,'treatment_action',w.allowed_actions())
        self.assertEqual(parsed['arguments']['pose'],[.1,.4,1.5,0,0,0])
        a=Adapter('crusoe');a.key='fake'
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(response).encode()
        with patch('urllib.request.urlopen',return_value=Reply()) as call:a.call(w.observations(),'data:image/png;base64,test')
        body=json.loads(call.call_args.args[0].data)
        self.assertEqual(body['tool_choice'],'required')
        schema=body['tools'][0]['function']['parameters']['properties']
        self.assertEqual(schema['action']['enum'],w.allowed_actions());self.assertIn('x',schema);self.assertNotIn('arguments',schema)

    def test_force_recovery_sequence_remains_productive(self):
        w=Manipulation(7,'precision');w.status='running';w.nonempty_scan=True;x,_,z=w.weed['position']
        def run(action,**args):
            command(w,action,**args);w.record_control_progress('motion_completed' if action in ('move_arm','return') else action)
        for force in (10,15,20,30):
            run('move_arm',pose=[x,.13,z,0,0,0]);frame(w)
            run('assess_alignment',frame_id=w.frame['id'],stem_between_fingers=True,depth_consistent=True,evidence='Fresh image shows central stem between both inner finger faces')
            run('set_gripper',opening=0,force=force);frame(w)
            self.assertNotIn('move_arm',w.allowed_actions())
            run('confirm_contact',frame_id=w.frame['id'],evidence='Actual holding and positive two newton load confirmed')
            run('move_arm',pose=[x,.33,z,0,0,0])
            if force<30:
                self.assertTrue(w.must_reopen);self.assertNotIn('move_arm',w.allowed_actions());run('open_gripper')
        self.assertTrue(w.extracted)
        run('move_arm',pose=[.95,.8,2.5,0,0,0]);run('open_gripper');frame(w)
        run('verify');self.assertTrue(w.stage_verified);run('return');frame(w);run('verify')
        self.assertTrue(all(w.verify().values()));self.assertEqual(w.status,'completed')
        self.assertEqual(sum(e['type']=='slip' for e in w.events),3)
        self.assertNotIn('grasp_geometry',w.observations())
        self.assertNotIn('26',w.observations()['instructions'])

    def test_stalled_holding_can_increase_force_and_reconfirm(self):
        from simulator.arm import ik
        w=Manipulation(7,'precision');w.status='running';w.nonempty_scan=True
        x,_,z=w.weed['position'];w.joints=ik([x,.13,z,0,0,0],w.base());frame(w)
        command(w,'assess_alignment',frame_id=w.frame['id'],stem_between_fingers=True,depth_consistent=True,evidence='Both inner fingers enclose the selected stem')
        command(w,'set_gripper',opening=0,force=10);frame(w)
        w.control_progress['recovery_required']=True
        command(w,'set_gripper',opening=0,force=30)
        self.assertTrue(w.holding);self.assertIsNone(w.contact_ack);frame(w)
        command(w,'confirm_contact',frame_id=w.frame['id'],evidence='Positive load and measured holding after force adjustment')
        self.assertIsNotNone(w.contact_ack)

    def test_crusoe_pose_without_optional_orientation_is_vertical(self):
        response={'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'treatment_action','arguments':json.dumps(dict(action='move_arm',reason='Approach the observed crown',x=.1,y=.4,z=1.6))}}]}}]}
        parsed=parse_response(response,'treatment_action',['move_arm'])
        self.assertEqual(parsed['arguments']['pose'],[.1,.4,1.6,0,0,0])
        del response['choices'][0]['message']['tool_calls'][0]['function']['arguments']
        with self.assertRaises(InferenceError):parse_response(response,'treatment_action',['move_arm'])
