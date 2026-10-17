"""Camera-guided irrigation and bounded physical delivery."""
import copy
from .common import RecordedWorld, uid, digest, finite, VERSION
from .camera import project_ground
from .png import components

class Treatment(RecordedWorld):
    kind='irrigation'
    frame_limit=12
    decision_limit=65

    def __init__(self,seed=7,trial='baseline'):
        self.id,self.seed,self.version=uid(),seed,VERSION
        self.trial=trial; self.time=0.0; self.seq=self.revision=0; self.status='paused'
        self.events=[]; self.receipts={}; self.prompt_versions={'treatment':'treatment-v1'}
        self.contract=dict(target_moisture=65,maximum_moisture=67,reserve=20,deadline=300,goal='Irrigate the root zone; verify and return')
        self.contract_hash=digest(self.contract)
        self.robot=dict(id='T1',position=[0,8],home=[0,8],battery=100.0,minimum_battery=100.0,water=30.0,lifecycle='idle',action=None,fault=None)
        self.phase='irrigation'; self.tool='nozzle'; self.moisture=23.0
        self.effective=0.0; self.delivered=0.0; self.dose_sequence=0; self.flow=None; self.moisture_reading=None
        self.aim=None; self.faults={}; self.observed_fault=None
        self.frame=None; self.frames=[]; self.frame_request=None; self.depth_request=None; self.scan=None
        self.decisions=0; self.return_verified=False; self.feedback='Ready for inspection'
        self.stage_inspections={}; self.event('created',seed=seed,contract_hash=self.contract_hash)

    def camera(self):
        x,z=self.robot['position']
        return dict(width=640,height=360,fov=58,near=.05,position=[x,1.2,z-.4],direction=[0,-.6,-4],up=[0,1,0])

    def request_frame(self):
        if self.frame_request: return self.frame_request
        if len(self.frames)>=self.frame_limit: raise ValueError('frame budget exhausted')
        self.frame_request=dict(id=uid(),mission_id=self.id,revision=self.revision,phase=self.phase,camera=self.camera())
        return self.frame_request

    def accept_frame(self,request_id,artifact):
        request=self.frame_request
        if not request or request['id']!=request_id or request['revision']!=self.revision: raise ValueError('stale or unsolicited frame')
        if not artifact.get('ready'): raise ValueError('frame must be durable')
        self.frame=dict(id=uid(),request_id=request_id,revision=self.revision,phase=self.phase,camera=request['camera'],dose_sequence=self.dose_sequence,artifact_id=artifact['id'],content_hash=artifact.get('sha256'),sim_time=self.time)
        self.frames.append(copy.deepcopy(self.frame)); self.frame_request=None
        self.stage_inspections[self.phase]=self.revision
        self.event('observation','T1',frame=self.frame)
        return self.frame

    def fresh(self,frame_id):
        if not self.frame or self.frame['id']!=frame_id or self.frame['revision']!=self.revision or self.frame['phase']!=self.phase: raise ValueError('fresh image from current phase required')
        return self.frame

    def invalidate(self):
        self.revision+=1; self.frame_request=None

    def allowed_actions(self):
        return ['capture_image','read_moisture','aim_nozzle','dispense','read_flow','service_tool','verify','return','stop']

    def observations(self):
        return dict(mission_id=self.id,kind=self.kind,status=self.status,phase=self.phase,trial=self.trial,mission=self.contract,
                    available_actions=self.allowed_actions(),resources={k:self.robot[k] for k in ('battery','water','position')},
                    tool=self.tool,frame=copy.deepcopy(self.frame),camera=self.camera(),feedback=self.feedback,
                    sensors=dict(moisture=self.moisture_reading,flow=self.flow,observed_fault=self.observed_fault),
                    budgets=dict(frames_remaining=self.frame_limit-len(self.frames),commands_remaining=self.decision_limit-self.decisions,time_remaining=300-self.time),history=[e for e in self.events if e['type'] in ('accepted','rejected','completed','slip','contact','extraction','deposit','dropped','verification','inference_error')][-8:])

    def command(self,command_id,robot,action,**args):
        if command_id in self.receipts: return copy.deepcopy(self.receipts[command_id])
        receipt=dict(command_id=command_id,robot_id=self.robot['id'],action=action,arguments=args,accepted=False,revision=self.revision)
        try:
            if self.status in ('completed','failed','aborted','blocked'): raise ValueError('mission terminal')
            if self.robot['action']: raise ValueError('physical action in progress')
            if self.decisions>=self.decision_limit or self.time>=300 or self.robot['battery']<=25:
                self.status='blocked'; raise ValueError('mission budget exhausted')
            self.decisions+=1
            self._action(action,args)
            receipt['accepted']=True
        except (ValueError,KeyError,TypeError) as exc:
            receipt['reason']=str(exc) if isinstance(exc,ValueError) else 'missing or invalid argument: '+str(exc.args[0])[:60] if isinstance(exc,KeyError) else 'invalid argument type'
            self.feedback=receipt['reason']
        self.receipts[command_id]=receipt
        if self.robot['action']: self.robot['action']['id']=command_id
        self.event('accepted' if receipt['accepted'] else 'rejected','T1',receipt=receipt)
        return copy.deepcopy(receipt)

    def _action(self,action,args):
        if action=='capture_image': self.request_frame()
        elif action=='approach':
            self.robot['action']=dict(kind='move_base',target=3.8); self.robot['lifecycle']='working'
        elif action=='read_moisture':
            self.moisture_reading=dict(value=self.moisture,dose_sequence=self.dose_sequence,revision=self.revision)
            self.feedback=f'Measured moisture {self.moisture:.2f}%'
        elif action=='read_flow':
            self.flow=dict(value=getattr(self,'last_flow',0),dose_sequence=self.dose_sequence)
            self.feedback=f'Measured last delivery {self.flow["value"]:.2f} L'
        elif action=='aim_nozzle':
            f=self.fresh(args['frame_id']); self.aim=project_ground(f['camera'],finite(args['u'],0,1),finite(args['v'],0,1))
            self.feedback='Nozzle aimed from calibrated image ray'
        elif action=='dispense':
            amount=finite(args['liters'],.01,5)
            if self.phase!='irrigation' or self.tool!='nozzle' or self.aim is None or not self.moisture_reading: raise ValueError('inspect, measure and aim first')
            self.fresh(args['frame_id'])
            if amount>self.robot['water']: raise ValueError('insufficient tank volume')
            self.robot['action']=dict(kind='water',remaining=amount,delivered=0.0,effective=0.0)
            self.dose_sequence+=1; self.invalidate(); self.robot['lifecycle']='working'
        elif action=='service_tool':
            if not self.observed_fault: raise ValueError('no observed tool fault')
            self.faults[self.tool]=False; self.observed_fault=None; self.robot['fault']=None; self.aim=None; self.invalidate(); self.feedback='Tool serviced; capture a fresh image'
        elif action=='verify':
            checks=self.verify(); self.feedback='Independent checks: '+str(checks)
            self.event('verification','T1',checks=checks)
            if all(checks.values()): self.status='completed'
        elif action=='return':
            self.robot['action']=dict(kind='move_base',target=8); self.robot['lifecycle']='working'
        elif action=='stop': self.status='aborted'
        else: raise ValueError('unknown tool')

    def tick(self,dt):
        finite(dt,0,60)
        while dt>1e-9 and self.status=='running' and self.robot['action']:
            step=min(.05,dt); dt-=step; self.time+=step; a=self.robot['action']; self.revision+=1
            self.robot['battery']-=step*.08; self.robot['minimum_battery']=min(self.robot['minimum_battery'],self.robot['battery'])
            if self.time>=300 or self.robot['battery']<=25:
                self.status='blocked'; self.feedback='Operating budget reached'; break
            done=False
            if a['kind']=='move_base':
                z=self.robot['position'][1]; delta=a['target']-z; d=min(abs(delta),step*1.8)
                self.robot['position'][1]+=d*(1 if delta>0 else -1)
                done=abs(delta)<=d+1e-9
                if done and a['target']==8: self.return_verified=True
            else: done=self.physical_step(a,step)
            if done:
                self.event('completed','T1',command_id=a.get('id'),result=copy.deepcopy(a))
                self.robot.update(action=None,lifecycle='idle')

    def physical_step(self,a,step):
        amount=min(step*2,a['remaining']); a['remaining']-=amount
        if self.faults.get(self.tool):
            self.observed_fault='nozzle clogged'; self.robot['fault']=self.observed_fault; self.feedback=self.observed_fault
        else:
            self.robot['water']-=amount; self.delivered+=amount; a['delivered']+=amount
            if self.aim and (self.aim[0]**2+self.aim[2]**2)**.5<.72:
                self.effective+=amount; self.moisture+=amount*2; a['effective']+=amount
        self.last_flow=a['delivered']
        return a['remaining']<1e-8

    def verify(self):
        before=any(f['dose_sequence']==0 for f in self.frames)
        after=any(f['dose_sequence']==self.dose_sequence and f['dose_sequence']>0 for f in self.frames)
        return dict(moisture=65-1e-6<=self.moisture<=67+1e-6,
                    delivery=self.effective>=21-1e-6 and self.flow is not None and self.flow['dose_sequence']==self.dose_sequence and self.flow['value']>0,
                    measured=self.moisture_reading is not None and self.moisture_reading['dose_sequence']==self.dose_sequence,
                    images=before and after,battery=self.robot['minimum_battery']>20,
                    returned=self.return_verified and abs(self.robot['position'][1]-8)<1e-6 and self.robot['action'] is None and digest(self.contract)==self.contract_hash)

    def snapshot(self):
        s=super().snapshot(); s.update(kind=self.kind,checks=self.verify(),camera=self.camera(),observations=self.observations()); return s

class PixelController:
    label='Offline PNG color heuristic'

    def decide(self,obs,pixels):
        frame=obs['frame']; phase=obs['phase']; sensors=obs['sensors']
        if obs['resources']['position'][1]>3.81 and not sensors['moisture']:
            return 'approach',{}
        if sensors.get('observed_fault'): return 'service_tool',{}
        if phase=='irrigation':
            if not sensors['moisture'] or frame and sensors['moisture']['dose_sequence']!=frame['dose_sequence']: return 'read_moisture',{}
            if sensors['moisture']['value']>=65-1e-6:
                if not sensors['flow'] or sensors['flow']['dose_sequence']!=sensors['moisture']['dose_sequence']: return 'read_flow',{}
                if obs['kind']=='care': return 'next_stage',{}
                if obs['resources']['position'][1]<7.99: return 'return',{}
                return 'verify',{}
            hits=components(pixels,'basin') if pixels else []
            if not hits: return 'capture_image',{}
            if not obs.get('aimed'): return 'aim_nozzle',dict(u=hits[0]['u'],v=hits[0]['v'],frame_id=frame['id'])
            return 'dispense',dict(liters=min(5,(65-sensors['moisture']['value'])/2),frame_id=frame['id'])
        if phase in ('weeds','pests'):
            tool='gripper' if phase=='weeds' else 'vacuum'
            if obs['tool']!=tool: return 'select_tool',dict(tool=tool)
            hits=components(pixels,'weed' if phase=='weeds' else 'pest') if pixels else []
            if hits: return 'remove_weed' if phase=='weeds' else 'remove_pest',dict(u=hits[0]['u'],v=hits[0]['v'],frame_id=frame['id'])
            return 'next_stage',{}
        if phase=='fertilizer':
            if obs['tool']!='fertilizer': return 'select_tool',dict(tool='fertilizer')
            meter=sensors.get('fertilizer')
            if not meter: return 'read_prescription',{}
            if meter['effective']>=meter['prescription']-1e-6: return 'next_stage',{}
            return 'fertilize',dict(grams=min(5,meter['prescription']-meter['effective']),frame_id=frame['id'])
        if phase=='return':
            if obs['resources']['position'][1]<7.99: return 'return',{}
            return 'verify',{}
        return 'verify',{}
