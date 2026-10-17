"""Articulated extraction. Contact, load, slip, extraction and collection are physical facts."""
import math
import random
from .treatment import Treatment
from .common import digest,finite
from .camera import add,sub,norm,matvec,project_ground
from .arm import fk,ik,trajectory,LIMITS
from . import lidar

STAGED={'alignment','wrist'}
TRIALS={'baseline','known','depth','lidar','alignment','wrist'}

class Manipulation(Treatment):
    kind='arm'; frame_limit=50; decision_limit=50

    def __init__(self,seed=7,trial='wrist'):
        if trial not in TRIALS: raise ValueError('invalid arm trial')
        super().__init__(seed,trial); self.phase='extraction'; self.tool='articulated gripper'; self.robot['position']=[0,3.8]
        rng=random.Random(seed+510)
        self.weed=dict(id='weed0',position=[rng.uniform(-.55,.5),.08,rng.uniform(1.15,1.65)],form=rng.choice(['grass','rosette','thistle']),size=rng.uniform(.9,1.2),leaves=rng.randint(9,15),rotation=rng.random()*math.tau,removed=False)
        self.protected=[dict(id='clover0',position=[-.85,.08,1.4]),dict(id='clover1',position=[.85,.08,1.4])]
        self.inventory_hash=digest(dict(weed=self.weed,protected=self.protected))
        self.joints=ik([0,.8,2.2,0,0,0],self.base())
        self.opening=.12; self.force=0; self.load=0; self.holding=False; self.extracted=False; self.deposited=False; self.grip_origin=None
        self.damage=[]; self.collision=None; self.alignment=None; self.contact_ack=None; self.must_reopen=False; self.nonempty_scan=False
        self.bin=[.95,.48,2.5]; self.initial_inventory=dict(weed=dict(self.weed),protected=self.protected)
        self.contract.update(goal='Extract the weed, collect in the bin, preserve protected plants and return',reserve=20)
        self.contract_hash=digest(self.contract)

    def base(self): return [self.robot['position'][0],.8,self.robot['position'][1]-.5]
    def tool_pose(self): return fk(self.joints,self.base())

    def camera(self):
        x,z=self.robot['position']
        if self.trial=='wrist' and hasattr(self,'joints'):
            pose=self.tool_pose(); r=pose['rotation']; p=pose['position']
            return dict(width=640,height=360,fov=70,near=.05,position=add(p,matvec(r,[0,.04,.22])),direction=matvec(r,[0,-.12,-.28]),up=matvec(r,[0,1,0]))
        if self.trial in ('depth','lidar','alignment'):
            return dict(width=640,height=360,fov=55,near=.05,position=[x+.75,1.15,z-.9],direction=[-.75,-.95,-1.45],up=[0,1,0])
        return dict(width=640,height=360,fov=45,near=.05,position=[x,1.8,z-.15],direction=[0,-1.45,-2.5],up=[0,1,0])

    def accept_frame(self,request_id,artifact):
        frame=super().accept_frame(request_id,artifact); self.alignment=None
        frame.update(extracted=self.extracted,deposited=self.deposited)
        self.frames[-1].update(extracted=self.extracted,deposited=self.deposited)
        return frame

    def allowed_actions(self):
        actions=['capture_image','move_arm','set_gripper','open_gripper','verify','return','stop']
        if self.trial in ('baseline','known'): actions+=['project_ground']
        if self.trial=='depth': actions+=['measure_depth']
        if self.trial in ('lidar','alignment','wrist'): actions+=['scan_lidar']
        if self.trial in STAGED: actions+=['assess_alignment','confirm_contact']
        return actions

    def observations(self):
        obs=super().observations()
        if not hasattr(self,'joints'): return obs
        obs.update(joints=self.joints,joint_limits=LIMITS,base=self.base(),tool_pose=self.tool_pose(),bin=self.bin,
                   gripper=dict(opening=self.opening,force=self.force,holding=self.holding,load=self.load,must_reopen=self.must_reopen,extracted=self.extracted,deposited=self.deposited),
                   protocol=dict(nonempty_scan=self.nonempty_scan,alignment=self.alignment,contact_acknowledged=self.contact_ack is not None),scan=self.scan,
                   scan_stale=self.scan is not None and self.scan['revision']!=self.revision)
        if self.trial=='known': obs['diagnostic_known_grasp']=[self.weed['position'][0],.15,self.weed['position'][2]]
        return obs

    def _action(self,action,args):
        if action=='move_arm':
            if self.trial in ('lidar','alignment','wrist') and not self.nonempty_scan: raise ValueError('initial nonempty LiDAR scan required')
            if self.must_reopen: raise ValueError('reopen after miss or slip before repositioning')
            if self.holding and self.trial in STAGED and self.contact_ack is None: raise ValueError('confirm actual contact with fresh image before carrying')
            end=ik(args['pose'],self.base(),self.joints) if 'pose' in args else args['joints']
            try: samples,duration=trajectory(self.joints,end,self.base())
            except ValueError as exc: self.collision=str(exc); raise
            self.collision=None; self.alignment=None
            self.robot['action']=dict(kind='arm',start=self.joints[:],end=end,duration=duration,elapsed=0)
            self.robot['lifecycle']='working'; self.invalidate()
        elif action=='assess_alignment':
            self.fresh(args['frame_id'])
            if self.trial not in STAGED: raise ValueError('assessment only in staged trials')
            if type(args['stem_between_fingers']) is not bool or type(args['depth_consistent']) is not bool: raise ValueError('strict boolean assessment required')
            self._evidence(args)
            self.alignment=dict(frame_id=args['frame_id'],revision=self.revision,aligned=args['stem_between_fingers'] and args['depth_consistent'],evidence=args['evidence'])
            self.feedback='Visual claim recorded; independent contact rules still apply'
        elif action=='confirm_contact':
            self.fresh(args['frame_id']); self._evidence(args)
            if not self.holding or self.load<=0: raise ValueError('no measured contact/load to confirm')
            self.contact_ack=dict(frame_id=args['frame_id'],revision=self.revision,force=self.force)
            self.feedback='Measured contact acknowledged'
        elif action in ('set_gripper','open_gripper'):
            opening=finite(args['opening'],0,.12) if action=='set_gripper' else .12
            force=finite(args['force'],0,45) if action=='set_gripper' else 0
            if self.trial in STAGED and opening<=.025 and not self.holding:
                if not self.alignment or not self.alignment['aligned'] or self.alignment['revision']!=self.revision: raise ValueError('fresh positive visual assessment required')
            was_holding=self.holding; self.opening=opening; self.force=force; self.contact_ack=None
            p=self.tool_pose()['position']; r=self.tool_pose()['rotation']
            tilt=math.degrees(math.acos(max(-1,min(1,r[1][1]))))
            if opening>.025 or force<8:
                if was_holding and self.extracted:
                    self.deposited=math.hypot(p[0]-self.bin[0],p[2]-self.bin[2])<.24 and .48<p[1]<1.3
                    self.event('deposit' if self.deposited else 'dropped','T1',collected=self.deposited)
                self.holding=False; self.load=0
                if opening>=.119: self.must_reopen=False
            elif not was_holding:
                horizontal=math.hypot(p[0]-self.weed['position'][0],p[2]-self.weed['position'][2])
                self.holding=horizontal<.055 and .09<=p[1]<=.22 and tilt<25 and not self.extracted
                if self.holding:
                    self.grip_origin=p[:]; self.load=2.0; self.event('contact','T1',force=force,load=self.load)
                else: self.must_reopen=True; self.feedback='No stem contact. Reopen, inspect and reposition.'
                for plant in self.protected:
                    if math.hypot(p[0]-plant['position'][0],p[2]-plant['position'][2])<.12 and p[1]<.3: self.damage.append(plant['id'])
                if math.hypot(p[0],p[2])<.25: self.damage.append('crop')
            self.alignment=None; self.invalidate()
        elif action=='project_ground':
            if self.trial not in ('baseline','known'): raise ValueError('ground projection unavailable')
            frame=self.fresh(args['frame_id']); self.feedback='Ground projection: '+str(project_ground(frame['camera'],args['u'],args['v']))
        elif action in ('scan_lidar','measure_depth'):
            frame=self.fresh(args['frame_id'])
            if action not in self.allowed_actions(): raise ValueError('sensor unavailable in this trial')
            self.depth_request=lidar.request(frame,args['u'],args['v'],args.get('span',.24))
            if action=='measure_depth': self.depth_request['rays']=[[finite(args['u'],0,1),finite(args['v'],0,1)]]
        elif action=='return':
            if self.holding: raise ValueError('collect the plant before returning')
            super()._action(action,args)
        else: super()._action(action,args)

    def _evidence(self,args):
        if not isinstance(args.get('evidence'),str) or not 8<=len(args['evidence'])<=600: raise ValueError('evidence must be 8..600 characters')

    def accept_depth(self,request_id,frame_id,revision,points,artifact):
        if not self.depth_request or revision!=self.revision: raise ValueError('stale depth request')
        accepted=lidar.validate(self.depth_request,request_id,frame_id,revision,points)
        if not artifact.get('ready'): raise ValueError('depth artifact not durable')
        self.scan=dict(frame_id=frame_id,revision=revision,points=accepted,bounds=self.depth_request['bounds'],artifact_id=artifact['id'])
        self.nonempty_scan=self.nonempty_scan or any(p is not None for p in accepted)
        self.depth_request=None; self.event('depth','T1',scan=self.scan)

    def physical_step(self,a,step):
        if a['kind']!='arm': return super().physical_step(a,step)
        a['elapsed']=min(a['duration'],a['elapsed']+step)
        t=a['elapsed']/a['duration']; self.joints=[x+(y-x)*t for x,y in zip(a['start'],a['end'])]
        p=self.tool_pose()['position']
        if self.holding:
            lift=p[1]-self.grip_origin[1]
            side=math.hypot(p[0]-self.grip_origin[0],p[2]-self.grip_origin[2])
            if not self.extracted and (side>.12 or lift>.08 and self.force<26):
                self.holding=False; self.load=0; self.must_reopen=True; self.contact_ack=None
                self.feedback='Grip slipped; reopen, observe and regrasp with sufficient force'; self.event('slip','T1',force=self.force,lift=lift)
                # A slip interrupts the remaining path at its actual sampled pose.
                return True
            if not self.extracted:
                self.load=2+max(0,lift)*100
                if lift>=.18:
                    self.extracted=True; self.weed['removed']=True; self.load=3
                    self.event('extraction','T1',lift=lift)
            else: self.load=3
        return a['elapsed']>=a['duration']-1e-9

    def verify(self):
        if not hasattr(self,'weed'): return {}
        inventory=dict(weed={**self.weed,'removed':False},protected=self.protected)
        return dict(extracted=self.extracted,collected=self.deposited and not self.holding,
                    images=any(not f.get('extracted') for f in self.frames) and any(f.get('deposited') for f in self.frames),
                    preserved=not self.damage,inventory=digest(inventory)==self.inventory_hash and digest(self.contract)==self.contract_hash,
                    battery=self.robot['minimum_battery']>20,
                    returned=self.return_verified and abs(self.robot['position'][1]-8)<1e-6 and self.robot['action'] is None)
