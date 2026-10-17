"""One durable orchard mission: measured care, articulated extraction and dock service."""
import copy
import math
from .orchard_manipulation import OrchardManipulation, TREES
from .manipulation import Manipulation
from .treatment import Treatment
from .arm import ik
from .camera import project_ground, ray
from .common import digest, distance, finite

CARE_GUIDE='''CARE MISSION: Complete each assigned tree; navigation and dock service are automatic after verification. Only the current stage's actions are available. Fresh images arrive AUTOMATICALLY after physical changes. Do not request another image to inspect what is already in the current image. Once no caterpillars remain visible, call next_stage for independent verification. EVERY tool call must include frame_id copied from the current frame, including inspect_tree, water_tree, fertilize_tree, next_stage and verify.
INSPECTION: inspect_tree records the fresh image and moisture/prescription meters.
IRRIGATION: A fixed service camera views the assigned trunk and root basin (world position in task_tree). aim_nozzle selects a visible ground point near the trunk with normalized image u,v and current frame_id. water_tree runs a metered, bounded dose to the measured 65% target; no liters argument. It consumes real tank volume and only moisture deposited within the root basin counts. Read moisture after delivery, then next_stage. A failed aim requires a new aim; don't water blindly.
FERTILIZER: The retained nozzle aim applies here too. fertilize_tree delivers exactly the remaining measured prescription, bounded by stock. Read_application after delivery, then next_stage. No grams argument is needed.
PESTS: The fixed service camera uses a close trunk view. Remove elongated purple/brown caterpillars with remove_pest(u,v,frame_id); preserve the round red ladybird. This tool projects the image ray onto the trunk contact surface, never snaps to an insect. Inspect the fresh image after each attempt. next_stage requires all pests physically removed; a claim alone cannot clear it.
EXTRACTION: Camera switches to the wrist and the staged grasp instructions apply. Scan actual surfaces; do not use the assigned tree's location as a weed target. After collection, verify completes this tree only if ALL care and preservation checks pass. The rover then goes to the dock for a metered refill, charge and bin unloading before the next tree. At the final dock, verify completes the entire mission. Never stop after only one tree.'''


class OrchardCare(OrchardManipulation):
    travel_lane=18.8
    crown_projection_required=True
    frame_limit=600
    decision_limit=700
    time_limit=3600
    wall_limit=5400
    cost_limit=10

    def __init__(self,seed=7,tree_count=10,worker='W1',assigned_task=None):
        if type(tree_count) is not int or not 1<=tree_count<=10:raise ValueError('tree_count must be 1..10')
        super().__init__(seed)
        self.mission_type='full_care';self.task_index=0;self.completed_trees=[];self.service_log=[]
        # Front boundary trees have a clear approach from the public south apron.
        trees=sorted((t for t in TREES if t['column']==12),key=lambda t:abs(t['row']-6))[:tree_count]
        self.tasks=[]
        for i,tree in enumerate(trees):
            specimen=Manipulation(seed+i,'precision');x,_,z=tree['position'];prefix=f'tree{i}-'
            weed=copy.deepcopy(specimen.weed);weed['render_seed']=(seed+i)*101;protected=copy.deepcopy(specimen.protected)
            for plant in [weed,*protected]:
                plant['id']=prefix+plant['id'];plant['position'][0]+=x;plant['position'][2]+=z
            pests=[dict(id=prefix+f'pest{j}',position=[x+(-.075 if j else .075),.45+j*.28,z+.205],removed=False) for j in range(2)]
            beneficial=[dict(id=prefix+'ladybird',position=[x-.08,1.15,z+.205])]
            self.tasks.append(dict(tree=tree,weed=weed,protected=protected,pests=pests,beneficial=beneficial,prescription=18+(seed+i)%5))
        if assigned_task is not None:self.tasks=[copy.deepcopy(assigned_task)]
        if worker not in self.parked or self.parked[worker]['role']!='worker':raise ValueError('unknown care worker')
        self.robot=copy.deepcopy(self.parked[worker]);self.robot.update(lifecycle='idle',water=30.)
        self.orchard['worker']=worker
        self.task_inventory_hash=digest(self.tasks)
        self.fertilizer_stock=40.;self.collected_total=0;self.unloaded_total=0
        self.contract.update(worker=worker,goal=f'{worker}: inspect, water, weed, fertilize and remove pests at {len(self.tasks)} trees; collect weeds, preserve plants and beneficial insects, then return to dock',tree_count=len(self.tasks),deadline=self.time_limit,wall_limit=self.wall_limit,cost_limit=self.cost_limit)
        self.contract_hash=digest(self.contract)
        self.load_task()

    def event(self,kind,robot=None,**payload):
        worker=getattr(self,'robot',{}).get('id','W1')
        # OrchardManipulation maps laboratory T1 to W1; remap at the final sink.
        from .common import RecordedWorld
        RecordedWorld.event(self,kind,worker if robot in ('T1','W1') else robot,**payload)

    def load_task(self):
        task=copy.deepcopy(self.tasks[self.task_index]);self.orchard.update(tree=task['tree'],arrived=False)
        x,_,z=task['tree']['position'];self.station=[x,z+3.8]
        self.weed=task['weed'];self.protected=task['protected'];self.pests=task['pests'];self.beneficial=task['beneficial']
        self.inventory_hash=digest(dict(weed=self.weed,protected=self.protected))
        self.initial_inventory=copy.deepcopy(dict(weed=self.weed,protected=self.protected))
        self.prescription=task['prescription'];self.fertilizer_delivered=0.;self.fertilizer_effective=0.;self.fertilizer_meter=None
        self.moisture=23.;self.effective=0.;self.delivered=0.;self.flow=None;self.moisture_reading=None;self.aim=None
        self.care_completed={};self.inspection=None;self.stage_verified=False
        self.holding=False;self.extracted=False;self.deposited=False;self.grip_origin=None;self.load=0.;self.force=0.;self.opening=.12
        self.alignment=None;self.contact_ack=None;self.must_reopen=False;self.missed_grasp=None;self.crown_projection=None;self.nonempty_scan=False;self.scan=None;self.depth_request=None
        self.return_verified=False;self.phase='travel';self.tool='service head';self.frame=None
        self.joints=ik([self.robot['position'][0],.8,self.robot['position'][1]-1.6,0,0,0],self.base())
        self.control_progress=None;self.record_control_progress('new_tree');self.invalidate()

    def camera(self):
        if getattr(self,'mission_type',None)=='full_care' and self.phase in ('inspection','irrigation','fertilizer','pests'):
            x,z=self.robot['position']
            return dict(width=640,height=360,fov=30 if self.phase=='pests' else 58,near=.05,position=[x+.75,1.2,z-.4],direction=[-.75,-.45,-3.28] if self.phase=='pests' else [-.75,-.6,-4],up=[0,1,0])
        return super().camera()

    def accept_frame(self,request_id,artifact):
        f=super().accept_frame(request_id,artifact)
        f['task_index']=self.task_index;self.frames[-1]['task_index']=self.task_index
        return f

    def record_control_progress(self,action):
        if getattr(self,'mission_type',None)=='full_care' and self.phase!='extraction':return self.control_progress
        return super().record_control_progress(action)

    def allowed_actions(self):
        if getattr(self,'mission_type',None)!='full_care':return super().allowed_actions()
        if self.phase in ('travel','service','return'):return ['stop']
        if self.phase=='final':return ['verify','stop']
        actions=['stop']
        if self.phase=='inspection':return actions+['inspect_tree']
        if self.phase=='irrigation':
            if self.moisture_reading is None or self.moisture_reading['dose_sequence']!=self.dose_sequence:return actions+['read_moisture']
            if self.moisture_reading['value']>=65-1e-6:return actions+['next_stage']
            return actions+['aim_nozzle']+(['water_tree'] if self.aim is not None else [])
        if self.phase=='fertilizer':
            if self.fertilizer_meter is None:return actions+['read_application']
            if self.fertilizer_meter['effective']>=self.fertilizer_meter['prescription']-1e-6:return actions+['next_stage']
            return actions+['aim_nozzle']+(['fertilize_tree'] if self.aim is not None else [])
        if self.phase=='pests':return actions+['remove_pest','next_stage']
        return super().allowed_actions()

    def observations(self):
        obs=super().observations()
        if getattr(self,'mission_type',None)!='full_care':return obs
        obs.update(care_progress=dict(tree_number=self.task_index+1,total=len(self.tasks),completed=len(self.completed_trees),stage=self.phase,stages_verified=list(self.care_completed)),service_camera=self.phase in ('inspection','irrigation','fertilizer','pests'))
        obs['sensors'].update(fertilizer=self.fertilizer_meter)
        obs['resources'].update(fertilizer_stock=self.fertilizer_stock)
        obs['aimed']=self.aim is not None;obs['nozzle_aim_world']=self.aim
        obs['instructions']=(('CURRENT TASK: wrist extraction. Other care stages are already verified. After depositing, verify starts the checked dock return automatically.\n'+obs['instructions']) if self.phase=='extraction' else CARE_GUIDE+'\n'+obs['instructions'])
        obs['worker']=self.robot['id']
        obs['instructions']=obs['instructions'].replace('W1',self.robot['id'])
        return obs

    def task_checks(self):
        checks=super().verify()
        frames=[f for f in self.frames if f.get('task_index')==self.task_index]
        checks['images']=any(not f.get('extracted') for f in frames) and any(f.get('deposited') for f in frames)
        checks.pop('returned',None)
        checks.update(inspected=self.inspection is not None,watered='irrigation' in self.care_completed and 65-1e-6<=self.moisture<=67+1e-6,
                      fertilized='fertilizer' in self.care_completed and abs(self.fertilizer_effective-self.prescription)<1e-6,
                      pests_removed='pests' in self.care_completed and all(p['removed'] for p in self.pests))
        return checks

    def verify(self):
        if getattr(self,'mission_type',None)!='full_care':return super().verify()
        complete=len(self.completed_trees)==len(self.tasks)
        return dict(trees_complete=complete,inspected=complete and all(t['checks']['inspected'] for t in self.completed_trees),
                    watered=complete and all(t['checks']['watered'] for t in self.completed_trees),
                    fertilized=complete and all(t['checks']['fertilized'] for t in self.completed_trees),
                    pests_removed=complete and all(t['checks']['pests_removed'] for t in self.completed_trees),
                    weeds_collected=complete and self.unloaded_total==len(self.tasks),
                    evidence=complete and all(t['checks']['images'] for t in self.completed_trees),
                    preserved=not self.damage,inventory=digest(self.tasks)==self.task_inventory_hash and digest(self.contract)==self.contract_hash,
                    battery=self.robot['minimum_battery']>25,
                    returned=complete and self.return_verified and distance(self.robot['position'],self.robot['home'])<1e-6 and self.robot['action'] is None)

    def _action(self,action,args):
        if action not in self.allowed_actions():raise ValueError('action unavailable in current care stage')
        if action=='inspect_tree':
            self.fresh(args['frame_id']);self.inspection=dict(frame_id=self.frame['id'],revision=self.revision)
            Treatment._action(self,'read_moisture',{});self.read_application();self.phase='irrigation';self.invalidate()
        elif action in ('water_tree','fertilize_tree'):
            self.fresh(args['frame_id'])
            if self.aim is None:raise ValueError('aim at the observed root basin first')
            tx,_,tz=self.orchard['tree']['position']
            if math.hypot(self.aim[0]-tx,self.aim[2]-tz)>=.72:raise ValueError('nozzle aim is outside the assigned 0.72 m root basin; reaim at the visible trunk base before dispensing')
            water=action=='water_tree';amount=(65-self.moisture)/2 if water else self.prescription-self.fertilizer_effective
            if amount<=1e-6:raise ValueError('target already reached; read meter then next_stage')
            if amount>(self.robot['water'] if water else self.fertilizer_stock):raise ValueError('insufficient stock')
            if water:self.dose_sequence+=1;self.moisture_reading=None
            else:self.fertilizer_meter=None
            self.robot['action']=dict(kind='care_water' if water else 'care_fertilizer',remaining=amount,delivered=0.,effective=0.)
            self.robot['lifecycle']='working';self.invalidate()
        elif action=='aim_nozzle':
            f=self.fresh(args['frame_id']);point=project_ground(f['camera'],finite(args['u'],0,1),finite(args['v'],0,1))
            if distance([point[0],point[2]],self.robot['position'])>4.5:raise ValueError('nozzle target outside 4.5 m reach')
            self.aim=point;self.feedback='Measured nozzle ground aim: '+str([round(v,3) for v in point])+'; compare with public task_tree root basin (radius 0.72 m)' 
        elif action=='read_application':self.read_application()
        elif action=='read_moisture':Treatment._action(self,action,args)
        elif action=='remove_pest':self.remove_pest(args)
        elif action=='next_stage':
            self.fresh(args['frame_id'])
            if self.phase=='irrigation':okay=65-1e-6<=self.moisture<=67+1e-6 and self.effective>=21-1e-6 and self.moisture_reading is not None and self.moisture_reading['dose_sequence']==self.dose_sequence
            elif self.phase=='fertilizer':okay=abs(self.fertilizer_effective-self.prescription)<1e-6 and self.fertilizer_meter is not None
            else:okay=all(p['removed'] for p in self.pests)
            if not okay or self.damage:raise ValueError('independent care checks reject stage clearance')
            self.care_completed[self.phase]=dict(revision=self.revision,frame_id=self.frame['id'])
            self.phase={'irrigation':'fertilizer','fertilizer':'pests','pests':'extraction'}[self.phase]
            self.tool='articulated gripper' if self.phase=='extraction' else 'service head'
            self.control_progress=None;self.invalidate();self.feedback='Care stage physically verified; inspect the new camera image'
        elif action=='verify':
            if self.phase=='final':
                checks=self.verify()
                if all(checks.values()):self.status='completed';self.feedback=f'All {len(self.tasks)} trees fully cared for; rover and collected weeds returned to dock'
            else:
                self.fresh(args.get('frame_id',self.frame['id'] if self.frame else None));checks=self.task_checks()
                if all(checks.values()):
                    self.stow()
                    self.completed_trees.append(dict(task_index=self.task_index,tree=self.orchard['tree'],checks=checks,inspection=self.inspection,stages=copy.deepcopy(self.care_completed),moisture=self.moisture,water=self.delivered,fertilizer=self.fertilizer_effective,completed_at=self.time))
                    self.collected_total+=1;self.stage_verified=True;self.phase='return'
                    self.event('tree_completed','W1',tree_number=self.task_index+1,checks=checks)
                else:self.feedback='Tree incomplete: '+str(checks)
            self.event('verification','W1',checks=checks)
        else:super()._action(action,args)

    def read_application(self):
        self.fertilizer_meter=dict(prescription=self.prescription,delivered=self.fertilizer_delivered,effective=self.fertilizer_effective,revision=self.revision)
        self.feedback=f'Measured fertilizer {self.fertilizer_effective:.2f}/{self.prescription} g; choose next_stage when the prescription is met'

    def stow(self):
        # A checked physical motion stows the tool before the chassis moves.
        from .arm import trajectory
        end=ik([self.robot['position'][0],.8,self.robot['position'][1]-1.6,0,0,0],self.base(),self.joints)
        samples,duration=trajectory(self.joints,end,self.base(),self.trunks)
        self.robot['action']=dict(kind='arm',start=self.joints[:],end=end,duration=duration,elapsed=0)
        self.event('arm_stow_started','W1',duration=duration)

    def remove_pest(self,args):
        f=self.fresh(args['frame_id']);d=ray(f['camera'],finite(args['u'],0,1),finite(args['v'],0,1));o=f['camera']['position']
        x,_,z=self.orchard['tree']['position'];ox,oz=o[0]-x,o[2]-z
        a=d[0]**2+d[2]**2;b=2*(ox*d[0]+oz*d[2]);c=ox**2+oz**2-.215**2;disc=b*b-4*a*c
        point=None
        if a>1e-12 and disc>=0:
            t=(-b-math.sqrt(disc))/(2*a)
            if t>0:point=[o[i]+d[i]*t for i in range(3)]
        self.feedback='No pest contact; inspect and change targeting'
        if point and .15<=point[1]<=1.6:
            for p in self.beneficial:
                if math.hypot(point[0]-p['position'][0],point[1]-p['position'][1])<=.10:self.damage.append(p['id'])
            for p in self.pests:
                if not p['removed'] and math.hypot(point[0]-p['position'][0],point[1]-p['position'][1])<=.10:
                    p['removed']=True;self.feedback='Pest removal contact confirmed';self.event('pest_removed','W1',task_index=self.task_index)
        self.robot['battery']-=.2;self.invalidate()

    def physical_step(self,a,step):
        if a['kind'] in ('care_water','care_fertilizer'):
            amount=min(step*2,a['remaining']);a['remaining']-=amount;a['delivered']+=amount
            x,_,z=self.orchard['tree']['position'];effective=self.aim is not None and math.hypot(self.aim[0]-x,self.aim[2]-z)<.72
            if a['kind']=='care_water':
                self.robot['water']-=amount;self.delivered+=amount
                if effective:self.effective+=amount;self.moisture+=amount*2
            else:
                self.fertilizer_stock-=amount;self.fertilizer_delivered+=amount
                if effective:self.fertilizer_effective+=amount
            if effective:a['effective']+=amount
            return a['remaining']<1e-8
        if a['kind']=='dock_service':
            a['remaining']-=step
            if a['remaining']>1e-8:return False
            self.service_log.append(dict(task_index=self.task_index,water_refill=30-self.robot['water'],fertilizer_refill=40-self.fertilizer_stock,charge=100-self.robot['battery'],time=self.time))
            self.robot['water']=30.;self.fertilizer_stock=40.;self.robot['battery']=100.;self.unloaded_total=self.collected_total
            if len(self.completed_trees)==len(self.tasks):
                self.return_verified=True;self.phase='final';self.feedback='All trees treated and bins unloaded. Verify mission at dock.'
            else:
                self.task_index+=1;self.load_task()
                a['next_station']=self.station[:]
            return True
        done=super().physical_step(a,step)
        if done and a['kind']=='navigate':
            if a['purpose']=='arrive':self.phase='inspection';self.feedback='Inspect the assigned tree before treatment'
            elif a['purpose']=='service':self.phase='service';self.return_verified=False
        return done

    def tick(self,dt):
        super().tick(dt)
        if self.status=='running' and self.robot['action'] is None:
            if self.phase=='return':self.navigate(self.robot['home'],'service')
            elif self.phase=='service':self.robot['action']=dict(kind='dock_service',remaining=15.)
            elif self.phase=='travel':self.begin()

    def snapshot(self):
        state=super().snapshot()
        state['vehicles']=copy.deepcopy(self.parked);state['vehicles'][self.robot['id']]=copy.deepcopy(self.robot)
        if getattr(self,'mission_type',None)=='full_care':
            # Renderer receives inventories; the provider receives observations only.
            done={t['task_index'] for t in self.completed_trees}
            state['weeds']=[];state['protected']=[];state['pests']=[];state['beneficial']=[]
            for i,task in enumerate(self.tasks):
                state['weeds'].append(copy.deepcopy(self.weed if i==self.task_index else dict(task['weed'],removed=i in done)))
                state['protected']+=copy.deepcopy(task['protected']);state['beneficial']+=copy.deepcopy(task['beneficial'])
                state['pests']+=copy.deepcopy(self.pests if i==self.task_index else [dict(p,removed=i in done) for p in task['pests']])
        return state
