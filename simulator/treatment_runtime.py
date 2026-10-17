"""Browser image/depth handshake and one outstanding multimodal decision."""
import base64
import time
from .runtime import Runtime
from .engine import TERMINAL
from .treatment import Treatment,PixelController
from .common import uid
from .inference import Adapter,InferenceError,TOOL_HELP,PROMPT
from .png import decode_url,crop_url
from . import lidar

class TreatmentRuntime(Runtime):
    def __init__(self,world=None,repository=None,config=None):
        self.scan_image=None;self.pixels=None; self.image=None; self.capture_started=None; self.depth_started=None; self.started_wall=None
        self.consecutive_invalid=0; self.last_miss=None; self.miss_count=0; self.frame_bytes={}; self.pending_artifacts=[]
        super().__init__(world or Treatment(),repository,config or dict(mode='pixels',engine='crusoe',speed=4))
        self.pixel_controller=PixelController()

    def start(self):
        if self.world.kind=='arm' and self.config['mode']!='vision': raise ValueError('arm experiments require live vision; scripted diagnostics are tests only')
        with self.lock:
            if hasattr(self.world,'begin') and self.world.status not in TERMINAL and not self.storage_error:self.world.begin()
            self.started_wall=time.monotonic(); super().start()

    def restore(self,session):
        super().restore(session)
        with self.lock:
            self.pixels=None; self.image=None; self.scan_image=None;self.frame_bytes={}
            self.capture_started=None;self.depth_started=None
            self.world.frame=None;self.world.frame_request=None;self.world.depth_request=None
            self.world.event('observation_required_after_restore',self.world.robot['id'])
            self.persist()

    def accept_frame(self,body):
        with self.lock:
            if getattr(self.world,'arena',None)=='orchard' and body.get('arena')!='orchard':raise ValueError('orchard sensor evidence required')
            if self.storage_error: raise ValueError('storage_blocked')
            if self.world.status in TERMINAL: raise ValueError('terminal sessions are read-only')
            if body.get('mission_id')!=self.world.id: raise ValueError('cross-mission frame')
            req=self.world.frame_request
            if not req or body.get('request_id')!=req['id'] or req['revision']!=self.world.revision: raise ValueError('stale capture request')
            raw,pixels=decode_url(body['data_url'])
            try:
                artifact=self.repository.artifact(self.world.id,self.world.robot['id'],'frame',raw,dict(request_id=req['id'],revision=req['revision'],camera=req['camera']))
            except Exception:
                self.storage_error='Frame artifact upload failed'; raise ValueError('storage_blocked') from None
            frame=self.world.accept_frame(req['id'],artifact); self.pending_artifacts.append(artifact)
            self.frame_bytes[frame['id']]=raw
            self.pixels=pixels; self.image='data:image/png;base64,'+base64.b64encode(raw).decode()
            self.capture_started=None; self.persist()
            return frame

    def accept_depth(self,body):
        with self.lock:
            if getattr(self.world,'arena',None)=='orchard' and body.get('arena')!='orchard':raise ValueError('orchard sensor evidence required')
            if self.storage_error: raise ValueError('storage_blocked')
            if self.world.status in TERMINAL: raise ValueError('terminal sessions are read-only')
            if body.get('mission_id')!=self.world.id or not self.world.depth_request: raise ValueError('cross-mission/unsolicited depth')
            req=self.world.depth_request
            if self.world.revision!=req['revision'] or not self.world.frame or self.world.frame['id']!=req['frame_id']: raise ValueError('stale or superseded scan frame')
            points=lidar.validate(req,body['request_id'],body['frame_id'],body['revision'],body['points'])
            artifacts=[];crop_data=None;crop_meta=None
            try:
                artifact=self.repository.artifact(self.world.id,self.world.robot['id'],'depth',points,dict(request_id=req['id'],frame_id=req['frame_id'],revision=req['revision'],camera=req['camera'],units='world meters'))
                artifacts.append(artifact)
                source=self.frame_bytes.get(req['frame_id'])
                if source:
                    crop,mapping=crop_url(source,req['bounds'])
                    crop_artifact=self.repository.artifact(self.world.id,self.world.robot['id'],'frame',crop,dict(subtype='scan_crop',source_frame_id=req['frame_id'],source_artifact_id=self.world.frame['artifact_id'],**mapping))
                    artifacts.append(crop_artifact)
                    crop_meta=dict(artifact_id=crop_artifact['id'],source_frame_id=req['frame_id'],**mapping)
                    crop_data='data:image/png;base64,'+base64.b64encode(crop).decode()
            except Exception:
                self.storage_error='Scan/crop artifact upload failed';raise ValueError('storage_blocked') from None
            self.world.accept_depth(req['id'],req['frame_id'],req['revision'],points,artifact)
            if crop_meta:self.world.scan['rgb_crop']=crop_meta
            self.scan_image=crop_data;self.pending_artifacts.extend(artifacts)
            self.depth_started=None; self.persist()
            return {'accepted':True}

    def step(self,elapsed):
        if self.storage_error: return
        w=self.world
        wall_limit=getattr(w,'wall_limit',240);cost_limit=getattr(w,'cost_limit',1)
        if self.active_wall>wall_limit and w.kind=='arm':
            w.status='blocked'; w.feedback=f'{wall_limit} wall-second mission cap'; w.event('blocked',reason=w.feedback); self.persist(); return
        if self.inference and sum(r['cost'] or 0 for r in self.inference)>=cost_limit:
            w.status='blocked'; w.feedback='Reported cost cap'; w.event('blocked',reason=w.feedback); self.persist(); return
        if w.robot['action']:
            if w.robot['action']['kind']=='navigate' and hasattr(self,'navigation_gate') and not self.navigation_gate.is_set():
                self.waiting='traffic_reservation';return
            dt=min(elapsed,.5)*4
            while dt>1e-8:
                if (w.robot['action'] or {}).get('kind')=='navigate' and hasattr(self,'navigation_gate') and not self.navigation_gate.is_set():
                    self.waiting='traffic_reservation';break
                part=min(.05,dt); dt-=part; w.tick(part); self.telemetry.sample(w,self.epoch)
            if not w.robot['action']:
                if w.kind=='arm':w.record_control_progress('motion_completed')
                self.persist()
            return
        if w.depth_request:
            if self.depth_started is None: self.depth_started=time.monotonic()
            if time.monotonic()-self.depth_started>30: raise ValueError('depth request timed out after 30 seconds')
            self.waiting='depth_wait'; return
        # The current PNG must correspond to current authoritative geometry.
        if w.frame is None or w.frame['revision']!=w.revision or w.frame['phase']!=w.phase or w.frame_request:
            if not w.frame_request:
                w.request_frame(); w.event('capture_requested',self.world.robot['id'],request=w.frame_request); self.persist()
            if self.capture_started is None: self.capture_started=time.monotonic()
            if time.monotonic()-self.capture_started>30: raise ValueError('camera request timed out after 30 seconds; keep the mission page open')
            self.waiting='sensor_wait'; return
        self.waiting=None
        if self.config['mode']=='pixels':
            obs=w.observations(); obs['aimed']=w.aim is not None
            action,args=self.pixel_controller.decide(obs,self.pixels)
            receipt=w.command(uid(),self.world.robot['id'],action,**args)
            self.consecutive_invalid=0 if receipt['accepted'] else self.consecutive_invalid+1
            if action in ('remove_weed','remove_pest') and w.feedback.startswith('No contact'):
                fingerprint=(action,w.frame.get('content_hash'))
                self.miss_count=self.miss_count+1 if fingerprint==self.last_miss else 1;self.last_miss=fingerprint
                if self.miss_count>=3:
                    w.status='blocked';w.feedback='Possible loop: three misses without changed image evidence or removal progress';w.event('loop_incident',self.world.robot['id'],reason=w.feedback)
            else: self.miss_count=0;self.last_miss=None
            if self.consecutive_invalid>=3: w.status='blocked'; w.feedback='Three rejected actions without physical progress'
            self.persist(); return
        entry=self.futures.get(self.world.robot['id'])
        if not entry and time.monotonic()<self.retry_after.get(self.world.robot['id'],0): self.waiting='inference_backoff';return
        if entry:
            session,future=entry
            if not future.done(): self.waiting='inference_wait'; return
            del self.futures[self.world.robot['id']]
            if session!=w.id: return
            try:
                result=self.consume(self.world.robot['id'],future); self.inference.append(result); self.failures[self.world.robot['id']]=0
                if sum(r['cost'] or 0 for r in self.inference)>=cost_limit:
                    w.status='blocked';w.feedback='Reported cost cap'
                    w.event('inference_discarded',self.world.robot['id'],result=result,reason=w.feedback);self.persist();return
                decision=result['decision']; w.event('decision',self.world.robot['id'],result=result,frame_id=w.frame['id'],prompt_version=w.prompt_versions)
                receipt=w.command(uid(),self.world.robot['id'],decision['action'],**decision['arguments'])
                if receipt['accepted'] and w.kind=='arm' and not w.robot['action']:w.record_control_progress(decision['action'])
                self.consecutive_invalid=0 if receipt['accepted'] else self.consecutive_invalid+1
                if self.consecutive_invalid>=3: w.status='blocked'; w.feedback='Three rejected actions without new progress'
            except InferenceError as exc:
                if exc.metrics: self.inference.append(exc.metrics)
                self.failures[self.world.robot['id']]=getattr(exc,'provider_failure_count',self.failures.get(self.world.robot['id'],0)+1)
                w.event('inference_error',self.world.robot['id'],error=str(exc))
                self.retry_after[self.world.robot['id']]=time.monotonic()+min(8,2**self.failures[self.world.robot['id']])
                if self.failures[self.world.robot['id']]>=3: w.status='blocked'; w.feedback=str(exc)
            self.persist(); return
        obs=w.observations(); obs['tool_arguments']={k:TOOL_HELP[k] for k in w.allowed_actions() if k in TOOL_HELP}
        if w.trial=='precision':
            obs.pop('tool_arguments',None) # The flat schema and wrist instructions define these fields.
        obs['budgets'].update(wall_seconds_remaining=max(0,wall_limit-self.active_wall),reported_dollars_remaining=max(0,cost_limit-sum(r['cost'] or 0 for r in self.inference)),cost_complete=all(r['cost'] is not None for r in self.inference))
        images=[self.image]
        obs['input_images']=[dict(index=0,meaning='Full current camera image',frame_id=w.frame['id'])]
        if self.scan_image and w.scan and w.scan['frame_id']==w.frame['id'] and not obs.get('scan_stale'):
            images.append(self.scan_image);obs['input_images'].append(dict(index=1,meaning='Magnified RGB crop of current scan bounds; use full-image u,v for actions',**w.scan['rgb_crop']))
        self.dispatch(self.world.robot['id'],'treatment',obs,images)
        self.waiting='inference_wait'
