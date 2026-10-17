"""Four-stage care with immutable inventories and independently checked contact."""
import math
import random
from .treatment import Treatment
from .common import digest,finite
from .camera import project_ground,ray,add,scale

class PlantCare(Treatment):
    kind='care'; frame_limit=64; decision_limit=240

    def __init__(self,seed=8,trial='baseline'):
        super().__init__(seed,trial)
        rng=random.Random(seed+300)
        self.weeds=[]; self.protected=[dict(id='clover0',position=[-.9,.08,.6]),dict(id='clover1',position=[.9,.08,.6])]
        count=0 if seed==0 else 3+seed%3
        # Rejection sampling provides actual geometric separation.
        for i in range(count):
            for _ in range(1000):
                x,z=rng.uniform(-1.05,1.05),rng.uniform(.95,1.65)
                if all(math.hypot(x-p['position'][0],z-p['position'][2])>=.4 for p in self.weeds+self.protected): break
            else: raise ValueError('cannot place inventory')
            self.weeds.append(dict(id=f'weed{i}',position=[x,.08,z],form=rng.choice(['grass','rosette','thistle']),size=rng.uniform(.8,1.1),leaves=rng.randint(9,15),rotation=rng.random()*math.tau,removed=False))
        self.pests=[dict(id=f'pest{i}',position=[(-.075 if i%2 else .075),.42+i*.23,.205],removed=False) for i in range(0 if seed==0 else 2+seed%2)]
        self.beneficial=[dict(id='ladybird',position=[-.08,1.17,.205])]
        self.damage=[]; self.prescription=18+seed%5; self.fertilizer_stock=40.0; self.fertilizer_delivered=0.0; self.fertilizer_effective=0.0; self.fertilizer_meter=None
        self.inventory_hash=digest(self.inventory()); self.stage_completed={}; self.last_attempt_revision={}

    def inventory(self):
        return dict(weeds=[{k:v for k,v in w.items() if k!='removed'} for w in self.weeds],pests=[{k:v for k,v in p.items() if k!='removed'} for p in self.pests],protected=self.protected,beneficial=self.beneficial,prescription=self.prescription)

    def camera(self):
        if getattr(self,'phase','')=='pests':
            return dict(width=640,height=360,fov=30,near=.05,position=[self.robot['position'][0],1.2,self.robot['position'][1]-.4],direction=[0,-.45,-3.28],up=[0,1,0])
        return super().camera()

    def allowed_actions(self):
        return super().allowed_actions()+['select_tool','remove_weed','remove_pest','read_prescription','read_application','fertilize','next_stage']

    def observations(self):
        obs=super().observations(); obs['sensors']['fertilizer']=self.fertilizer_meter; obs['resources']['fertilizer_stock']=self.fertilizer_stock
        obs['aimed']=self.aim is not None
        return obs

    def _action(self,action,args):
        if action=='select_tool':
            tool=args['tool']
            if tool not in ('nozzle','gripper','fertilizer','vacuum'): raise ValueError('unknown fitted tool')
            self.tool=tool; self.invalidate(); self.feedback=f'{tool} fitted; inspect again'
        elif action in ('remove_weed','remove_pest'):
            stage='weeds' if action=='remove_weed' else 'pests'; tool='gripper' if stage=='weeds' else 'vacuum'
            if self.phase!=stage or self.tool!=tool: raise ValueError('wrong phase/tool')
            f=self.fresh(args['frame_id']); u,v=finite(args['u'],0,1),finite(args['v'],0,1)
            if stage=='weeds':
                point=project_ground(f['camera'],u,v); radius=.19; dims=(0,2); targets=self.weeds; protected=self.protected
                if math.hypot(point[0]-self.robot['position'][0],point[2]-self.robot['position'][1])>3.2: raise ValueError('outside tool reach')
            else:
                direction=ray(f['camera'],u,v); origin=f['camera']['position']
                # Visible front of cylindrical trunk; no snapping to an insect.
                a=direction[0]**2+direction[2]**2; b=2*(origin[0]*direction[0]+origin[2]*direction[2]); c=origin[0]**2+origin[2]**2-.215**2
                discriminant=b*b-4*a*c
                if discriminant<0: point=None
                else:
                    t=(-b-math.sqrt(discriminant))/(2*a); point=add(origin,scale(direction,t)) if t>0 else None
                radius=.10; dims=(0,1); targets=self.pests; protected=self.beneficial
                if point and not .15<=point[1]<=1.6: raise ValueError('outside vacuum reach')
            self.invalidate(); self.last_attempt_revision[stage]=self.revision
            if self.faults.get(tool):
                self.observed_fault=f'{tool} jam'; self.robot['fault']=self.observed_fault; self.feedback=self.observed_fault
            else:
                self.feedback='No contact; inspect and target again'
                if point:
                    def near(t): return math.hypot(*(point[i]-t['position'][i] for i in dims))<=radius
                    if stage=='weeds' and math.hypot(point[0],point[2])<.25: self.damage.append('crop')
                    self.damage.extend(p['id'] for p in protected if near(p))
                    for target in targets:
                        if not target['removed'] and near(target):
                            target['removed']=True; self.feedback='Physical contact and removal confirmed'
                            self.event('removed','T1',stage=stage)
            self.robot['battery']-=.2; self.robot['minimum_battery']=min(self.robot['minimum_battery'],self.robot['battery']); self.time+=1
        elif action in ('read_prescription','read_application'):
            self.fertilizer_meter=dict(prescription=self.prescription,delivered=self.fertilizer_delivered,effective=self.fertilizer_effective,revision=self.revision)
            self.feedback='Saved prescription and cumulative application meter read'
        elif action=='fertilize':
            if self.phase!='fertilizer' or self.tool!='fertilizer' or not self.fertilizer_meter: raise ValueError('fit fertilizer tool and read prescription')
            self.fresh(args['frame_id']); amount=finite(args['grams'],.01,5)
            if amount>self.prescription-self.fertilizer_effective+1e-6 or amount>self.fertilizer_stock: raise ValueError('overdose or stock guard')
            self.robot['action']=dict(kind='fertilizer',remaining=amount,delivered=0.0,effective=0.0)
            self.robot['lifecycle']='working'; self.fertilizer_meter=None; self.invalidate()
        elif action=='next_stage':
            if not self.frame or self.frame['phase']!=self.phase or self.frame['revision']!=self.revision: raise ValueError('fresh stage inspection required')
            if self.phase=='irrigation': okay=all(v for k,v in super().verify().items() if k!='returned')
            elif self.phase=='weeds': okay=all(w['removed'] for w in self.weeds)
            elif self.phase=='fertilizer': okay=self.fertilizer_meter is not None and abs(self.fertilizer_effective-self.prescription)<1e-6
            elif self.phase=='pests': okay=all(p['removed'] for p in self.pests)
            else: raise ValueError('no next stage')
            if not okay or self.damage: raise ValueError('independent stage checks reject clearance')
            self.stage_completed[self.phase]=self.revision
            self.phase={'irrigation':'weeds','weeds':'fertilizer','fertilizer':'pests','pests':'return'}[self.phase]
            self.invalidate(); self.feedback='Stage independently verified'
        else: super()._action(action,args)

    def physical_step(self,a,step):
        if a['kind']!='fertilizer': return super().physical_step(a,step)
        amount=min(step*2,a['remaining']); a['remaining']-=amount
        if self.faults.get('fertilizer'):
            self.observed_fault='fertilizer jam'; self.robot['fault']=self.observed_fault
        else:
            self.fertilizer_stock-=amount; self.fertilizer_delivered+=amount; a['delivered']+=amount
            # Bounded nozzle action at the measured basin; no articulated fertilizer arm.
            if self.aim and math.hypot(self.aim[0],self.aim[2])<.72:
                self.fertilizer_effective+=amount; a['effective']+=amount
        return a['remaining']<1e-8

    def verify(self):
        checks=super().verify()
        if not hasattr(self,'weeds'): return checks
        checks.update(weeds=all(w['removed'] for w in self.weeds) and 'weeds' in self.stage_completed,
                      fertilizer=abs(self.fertilizer_effective-self.prescription)<1e-6 and self.fertilizer_meter is not None and 'fertilizer' in self.stage_completed,
                      pests=all(p['removed'] for p in self.pests) and 'pests' in self.stage_completed,
                      inventory=digest(self.inventory())==self.inventory_hash and digest(self.contract)==self.contract_hash,
                      preserved=not self.damage)
        return checks
