"""Browser image/depth handshake and one outstanding multimodal decision."""
import base64
import time
from .runtime import Runtime
from .treatment import Treatment,PixelController
from .common import uid
from .inference import Adapter,InferenceError,TOOL_HELP,PROMPT
from .png import decode_url
from . import lidar

class TreatmentRuntime(Runtime):
    def __init__(self,world=None,repository=None,config=None):
        self.pixels=None; self.image=None; self.capture_started=None; self.depth_started=None; self.started_wall=None
        self.consecutive_invalid=0; self.frame_bytes={}; self.pending_artifacts=[]
        super().__init__(world or Treatment(),repository,config or dict(mode='pixels',engine='crusoe',speed=4))
        self.pixel_controller=PixelController()

    def start(self):
        if self.world.kind=='arm' and self.config['mode']!='vision': raise ValueError('arm experiments require live vision; scripted diagnostics are tests only')
        self.started_wall=time.monotonic(); super().start()

    def restore(self,session):
        super().restore(session)
        with self.lock:
            self.pixels=None; self.image=None; self.frame_bytes={}
            self.capture_started=None;self.depth_started=None
            self.world.frame=None;self.world.frame_request=None;self.world.depth_request=None
            self.world.event('observation_required_after_restore','T1')
            self.persist()

    def accept_frame(self,body):
        with self.lock:
            if self.storage_error: raise ValueError('storage_blocked')
            if body.get('mission_id')!=self.world.id: raise ValueError('cross-mission frame')
            req=self.world.frame_request
            if not req or body.get('request_id')!=req['id'] or req['revision']!=self.world.revision: raise ValueError('stale capture request')
            raw,pixels=decode_url(body['data_url'])
            try:
                artifact=self.repository.artifact(self.world.id,'T1','frame',raw,dict(request_id=req['id'],revision=req['revision'],camera=req['camera']))
            except Exception:
                self.storage_error='Frame artifact upload failed'; raise ValueError('storage_blocked') from None
            frame=self.world.accept_frame(req['id'],artifact); self.pending_artifacts.append(artifact)
            self.frame_bytes[frame['id']]=raw
            self.pixels=pixels; self.image='data:image/png;base64,'+base64.b64encode(raw).decode()
            self.capture_started=None; self.persist()
            return frame

    def accept_depth(self,body):
        with self.lock:
            if self.storage_error: raise ValueError('storage_blocked')
            if body.get('mission_id')!=self.world.id or not self.world.depth_request: raise ValueError('cross-mission/unsolicited depth')
            req=self.world.depth_request
            if self.world.revision!=req['revision']: raise ValueError('stale scan')
            points=lidar.validate(req,body['request_id'],body['frame_id'],body['revision'],body['points'])
            artifact=self.repository.artifact(self.world.id,'T1','depth',points,dict(request_id=req['id'],frame_id=req['frame_id'],revision=req['revision'],camera=req['camera'],units='world meters'))
            self.world.accept_depth(req['id'],req['frame_id'],req['revision'],points,artifact)
            self.pending_artifacts.append(artifact); self.depth_started=None; self.persist()
            return {'accepted':True}

    def step(self,elapsed):
        if self.storage_error: return
        w=self.world
        if self.active_wall>240 and w.kind=='arm':
            w.status='blocked'; w.feedback='240 wall-second experiment cap'; w.event('blocked',reason=w.feedback); self.persist(); return
        if self.inference and sum(r['cost'] or 0 for r in self.inference)>=1:
            w.status='blocked'; w.feedback='Reported cost cap'; w.event('blocked',reason=w.feedback); self.persist(); return
        if w.robot['action']:
            dt=min(elapsed,.5)*4
            while dt>1e-8:
                part=min(.05,dt); dt-=part; w.tick(part); self.telemetry.sample(w,self.epoch)
            if not w.robot['action']: self.persist()
            return
        if w.depth_request:
            if self.depth_started is None: self.depth_started=time.monotonic()
            if time.monotonic()-self.depth_started>30: raise ValueError('depth request timed out after 30 seconds')
            self.waiting='depth_wait'; return
        # The current PNG must correspond to current authoritative geometry.
        if w.frame is None or w.frame['revision']!=w.revision or w.frame['phase']!=w.phase or w.frame_request:
            if not w.frame_request:
                w.request_frame(); w.event('capture_requested','T1',request=w.frame_request); self.persist()
            if self.capture_started is None: self.capture_started=time.monotonic()
            if time.monotonic()-self.capture_started>30: raise ValueError('camera request timed out after 30 seconds; keep treatment page open')
            self.waiting='sensor_wait'; return
        self.waiting=None
        if self.config['mode']=='pixels':
            obs=w.observations(); obs['aimed']=w.aim is not None
            action,args=self.pixel_controller.decide(obs,self.pixels)
            receipt=w.command(uid(),'T1',action,**args)
            self.consecutive_invalid=0 if receipt['accepted'] else self.consecutive_invalid+1
            if self.consecutive_invalid>=3: w.status='blocked'; w.feedback='Three rejected actions without physical progress'
            self.persist(); return
        entry=self.futures.get('T1')
        if entry:
            session,future=entry
            if not future.done(): self.waiting='inference_wait'; return
            del self.futures['T1']
            if session!=w.id: return
            try:
                result=future.result(); self.inference.append(result); self.failures['T1']=0
                decision=result['decision']; w.event('decision','T1',result=result,frame_id=w.frame['id'],prompt_version=w.prompt_versions)
                receipt=w.command(uid(),'T1',decision['action'],**decision['arguments'])
                self.consecutive_invalid=0 if receipt['accepted'] else self.consecutive_invalid+1
                if self.consecutive_invalid>=3: w.status='blocked'; w.feedback='Three rejected actions without new progress'
            except InferenceError as exc:
                if exc.metrics: self.inference.append(exc.metrics)
                self.failures['T1']=self.failures.get('T1',0)+1; w.event('inference_error','T1',error=str(exc))
                if self.failures['T1']>=3: w.status='blocked'; w.feedback=str(exc)
            self.persist(); return
        obs=w.observations(); obs['tool_arguments']={k:TOOL_HELP[k] for k in w.allowed_actions() if k in TOOL_HELP}
        self.futures['T1']=(w.id,self.executor.submit(Adapter(self.config['engine']).call,obs,self.image,getattr(w,'prompt_texts',{}).get('treatment',PROMPT)))
        self.waiting='inference_wait'
