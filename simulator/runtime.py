"""One writer per session, persistence barriers, wall clock and role-call executor."""
import concurrent.futures
import copy
import threading
import time
from .common import uid
from .engine import Mission,TERMINAL
from .agents import DemoController
from .persistence import Repository,StorageError
from .telemetry import Telemetry
from .inference import Adapter,InferenceError

class Runtime:
    def __init__(self,world=None,repository=None,config=None):
        self.lock=threading.RLock(); self.world=world or Mission(); self.repository=repository or Repository()
        self.config=config or dict(mode='demo',engine='crusoe',speed=8)
        self.committed=0; self.epoch=0; self.persisted=False; self.storage_error=None; self.pending=None
        self.telemetry=Telemetry(); self.controller=DemoController(); self.executor=concurrent.futures.ThreadPoolExecutor(max_workers=7)
        self.futures={}; self.inference=[]; self.failures={}; self.waiting=None; self.closed=False; self.last_commit=0
        self.thread=threading.Thread(target=self.loop,daemon=True); self.thread.start()

    def persist(self):
        try:
            if not self.persisted:
                lease=self.repository.create(self.world,self.config); self.epoch=lease['resume_epoch']; self.persisted=True
            if self.pending is None:
                self.world.event('checkpoint',status=self.world.status)
                artifacts=self.telemetry.flush(self.repository,self.world)
                artifacts+=getattr(self,'pending_artifacts',[])
                self.pending=self.repository.batch(self.world,self.committed,list(self.telemetry.latest.values()),artifacts)
            result=self.repository.commit(self.pending)
            self.committed=result['sequence']; self.pending=None; self.storage_error=None
            self.telemetry.motion=[]; self.pending_artifacts=[]; self.last_commit=time.monotonic()
            return True
        except StorageError as exc:
            self.storage_error=str(exc); self.waiting='storage_blocked'
            return False

    def start(self):
        with self.lock:
            if self.storage_error: raise ValueError('retry storage before starting')
            if self.world.status in TERMINAL: raise ValueError('create a new session after terminal outcome')
            self.world.status='running'; self.world.event('started',mode=self.config['mode'])
            self.persist()

    def pause(self,status='paused'):
        with self.lock:
            self.world.status=status; self.world.event(status)
            self.persist()

    def retry(self):
        with self.lock:
            # Renew the same writer lease; never overwrite another writer's session.
            if self.persisted: self.repository.lease(self.world.id)
            if self.persist():
                self.world.status='paused'; self.world.event('storage_recovered'); self.persist()

    def command(self,robot,action,args=None,command_id=None):
        with self.lock:
            if self.storage_error: raise ValueError('storage_blocked')
            receipt=self.world.command(command_id or uid(),robot,action,**(args or {}))
            self.persist() # Acceptance is durable before the next physical tick.
            return receipt

    def restore(self,session):
        with self.lock:
            state=self.repository.restore(session); lease=self.repository.lease(session)
            cls=type(self.world); self.world=cls.restore(state); self.world.status='paused'
            self.committed=lease['sequence']; self.epoch=lease['resume_epoch']; self.persisted=True
            self.pending=None; self.storage_error=None; self.telemetry=Telemetry()
            # Per-robot sequence resumes monotonically.
            for row in self.repository.read('robot_sessions',f'session_id=eq.{session}&limit=10'):
                self.telemetry.sequences[row['robot_id']]=row['sequence']
            self.world.event('restored',resume_epoch=self.epoch); self.persist()

    def _demo(self):
        decisions=self.controller.decisions(self.world.observations())
        for robot,action,args in decisions:
            self.world.command(uid(),robot,action,**args)
        if all(self.world.verify().values()): self.world.command(uid(),'orchestrator','claim_complete')
        if decisions or self.world.status=='completed': self.persist()

    def _live(self):
        now=time.monotonic()
        for robot,(session,future) in list(self.futures.items()):
            if not future.done(): continue
            del self.futures[robot]
            if session!=self.world.id or self.world.status!='running': continue
            try:
                result=future.result(); self.inference.append(result); self.failures[robot]=0
                decision=result['decision']; args=decision['arguments']
                self.world.event('decision',robot,result=result,prompt_version=self.world.prompt_versions)
                self.world.command(uid(),robot,decision['action'],**args); self.persist()
            except InferenceError as exc:
                self.failures[robot]=self.failures.get(robot,0)+1; self.world.event('inference_error',robot,error=str(exc))
                if self.failures[robot]>=3: self.world.status='blocked'
                self.persist()
        obs=self.world.observations()
        # Deterministic feasible option enumeration constrains role calls, but does not choose for a model.
        candidates=self.controller.decisions(obs)
        grouped={}
        for robot,action,args in candidates: grouped.setdefault(robot,[]).append(dict(action=action,arguments=args))
        if all(self.world.verify().values()): grouped['orchestrator']=[dict(action='claim_complete',arguments={})]
        for robot,options in grouped.items():
            if robot in self.futures or self.world.status!='running': continue
            role='orchestrator' if robot=='orchestrator' else 'retriever' if robot=='R1' else 'worker'
            permitted=dict(observation=obs,role=role,robot=robot,feasible_options=options)
            future=self.executor.submit(Adapter(self.config['engine'],role).call,permitted)
            self.futures[robot]=(self.world.id,future)

    def step(self,elapsed):
        if self.config['mode']=='demo': self._demo()
        else: self._live()
        if self.storage_error or self.world.status!='running': return
        dt=min(elapsed,.1)*self.config.get('speed',8)
        while dt>1e-8:
            part=min(.05,dt); dt-=part; self.world.tick(part)
            self.telemetry.sample(self.world,self.epoch)
        self.waiting='inference_wait' if self.futures else None

    def loop(self):
        previous=time.monotonic()
        while not self.closed:
            time.sleep(.05); now=time.monotonic(); elapsed=now-previous; previous=now
            with self.lock:
                try:
                    if self.storage_error: continue
                    if self.world.status=='running': self.step(elapsed)
                    if self.persisted and now-self.telemetry.last_heartbeat>=1:
                        self.telemetry.sample(self.world,self.epoch,True,self.waiting)
                    if self.persisted and self.world.seq>self.committed and now-self.last_commit>=.5: self.persist()
                except (ValueError,StorageError,InferenceError) as exc:
                    self.world.status='blocked'; self.world.event('blocked',error=str(exc)); self.persist()
                except Exception:
                    self.world.status='blocked'; self.world.event('blocked',error='Internal runtime error; inspect server diagnostics'); self.persist()

    def snapshot(self):
        with self.lock:
            state=self.world.snapshot(); state['events']=state['events'][-100:]
            state.update(config=self.config,storage=dict(healthy=not self.storage_error,error=self.storage_error,committed_sequence=self.committed),telemetry=self.telemetry.latest,
                         inference=dict(calls=len(self.inference),tokens=sum(r['usage'].get('total_tokens',0) for r in self.inference),cost=sum(r['cost'] for r in self.inference) if self.inference and all(r['cost'] is not None for r in self.inference) else None,results=self.inference[-30:]),waiting=self.waiting)
            if self.storage_error: state['status']='storage_blocked'
            return state

    def close(self):
        self.closed=True
        for _,future in self.futures.values(): future.cancel()
        self.executor.shutdown(wait=False,cancel_futures=True)
