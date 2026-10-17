"""One orchard worker owns navigation, grasping and its durable weed inventory."""
import copy
import json
from pathlib import Path
from .manipulation import Manipulation
from .engine import Mission
from .common import digest,uid,distance
from .arm import ik

TREES=json.loads(Path(__file__).with_name('orchard_trees.json').read_text())

class OrchardManipulation(Manipulation):
    def __init__(self,seed=7,trial='precision',growth=None):
        if trial!='precision':raise ValueError('orchard weeding uses the precision wrist controller')
        super().__init__(seed,trial)
        # A season day sets the weed's rendered growth stage; grasp physics are unchanged.
        if growth:self.weed.update(size=growth['size'],leaves=growth['leaves'],render_seed=seed*101%2**31)
        tree=next(t for t in TREES if t['row']==6 and t['column']==12)
        x,_,z=tree['position']
        self.arena='orchard';self.orchard=dict(tree=tree,worker='W1',arrived=False)
        self.trunks=[[t['position'][0],t['position'][2]] for t in TREES]
        self.station=[x,z+3.8]
        self.parked=Mission(seed).vehicles
        self.robot=copy.deepcopy(self.parked['W1'])
        self.robot['water']=30.0
        self.phase='travel';self.feedback='W1 ready to drive to the assigned orchard tree'
        for plant in [self.weed,*self.protected]:
            plant['position'][0]+=x;plant['position'][2]+=z
        self.bin_offset=[.95,.48,-1.3];self.update_bin()
        self.joints=ik([self.robot['position'][0],.8,self.robot['position'][1]-1.6,0,0,0],self.base())
        self.inventory_hash=digest(dict(weed=self.weed,protected=self.protected))
        self.initial_inventory=copy.deepcopy(dict(weed=self.weed,protected=self.protected))
        self.contract.update(goal='W1: drive to the orchard tree, extract and collect the weed, preserve plants and return to its dock',arena='orchard',worker='W1',tree=tree)
        self.contract_hash=digest(self.contract)
        self.control_progress=None;self.record_control_progress('initial')

    def event(self,kind,robot=None,**payload):
        super().event(kind,'W1' if robot=='T1' else robot,**payload)

    def begin(self):
        if self.phase=='travel' and not self.robot['action']:
            self.navigate(self.station,'arrive')

    def navigate(self,target,purpose):
        start=self.robot['position']
        lane=getattr(self,'travel_lane',18)
        route=[[start[0],lane],[target[0],lane],target[:]]
        length=sum(distance(a,b) for a,b in zip([start]+route,route))
        if self.robot['battery']-length*.13<=25:raise ValueError('navigation reserve guard')
        self.robot.update(lifecycle='working',action=dict(kind='navigate',route=route,purpose=purpose,id=uid()))
        self.invalidate();self.event('navigation_started','W1',purpose=purpose,route=route)

    def update_bin(self):
        x,z=self.robot['position'];self.bin=[x+self.bin_offset[0],self.bin_offset[1],z+self.bin_offset[2]]

    def allowed_actions(self):
        if getattr(self,'phase',None)=='travel':return ['stop']
        return super().allowed_actions()

    def _action(self,action,args):
        if action=='return':
            if not self.stage_verified or self.holding:raise ValueError('verify collection before returning')
            self.phase='return';self.navigate(self.robot['home'],'return')
        else:super()._action(action,args)

    def physical_step(self,a,step):
        if a['kind']!='navigate':return super().physical_step(a,step)
        target=a['route'][0];p=self.robot['position'];length=distance(p,target);travel=min(length,step*1.8)
        if length:
            end=[p[i]+(target[i]-p[i])*travel/length for i in range(2)]
            if any(distance(end,t)<.85 for t in self.trunks):
                self.status='blocked';self.feedback='Rover route blocked by a tree';return True
            self.robot['position']=end;self.robot['battery']-=travel*.13
        self.update_bin()
        if length<=travel+1e-9:a['route'].pop(0)
        if a['route']:return False
        if a['purpose']=='arrive':
            self.orchard['arrived']=True;self.phase='extraction';self.feedback='W1 parked; inspect the actual orchard with the wrist camera'
        else:self.return_verified=True;self.feedback='W1 returned to its dock; verify completion'
        return True

    def tick(self,dt):
        super().tick(dt)
        self.robot['minimum_battery']=min(self.robot['minimum_battery'],self.robot['battery'])
        self.update_bin()

    def observations(self):
        obs=super().observations()
        if hasattr(self,'arena'):
            obs.update(arena='orchard',worker='W1',task_tree=self.orchard['tree'])
            obs['instructions']+=' ORCHARD: You are the wrist controller on W1, parked at its assigned tree. All measurements and Cartesian commands use orchard WORLD coordinates, not tree-local offsets. Other orchard vegetation is visible. Use the current bin coordinates for collection. Return drives W1 to its dock after collection verification.'
        return obs

    def verify(self):
        checks=super().verify()
        if hasattr(self,'arena'):
            checks['returned']=self.return_verified and distance(self.robot['position'],self.robot['home'])<1e-6 and self.robot['action'] is None
            checks['inventory']=checks['inventory'] and self.trunks==[[t['position'][0],t['position'][2]] for t in TREES]
        return checks

    def snapshot(self):
        state=super().snapshot()
        if hasattr(self,'parked'):
            state['vehicles']=copy.deepcopy(self.parked);state['vehicles']['W1']=copy.deepcopy(self.robot)
        return state
