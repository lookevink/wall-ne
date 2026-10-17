"""One writer per session, persistence barriers, wall clock and role-call executor."""
import concurrent.futures
import copy
import threading
import time
from .common import uid,digest
from .engine import Mission,TERMINAL
from .agents import DemoController
from .persistence import Repository,StorageError
from .telemetry import Telemetry
from .inference import Adapter,InferenceError,PROMPT

class Runtime:
    def __init__(self,world=None,repository=None,config=None):
        self.lock=threading.RLock(); self.world=world or Mission(); self.repository=Repository(repository.url,repository.key) if isinstance(repository,Repository) else repository or Repository()
        self.config=copy.deepcopy(config or dict(mode='demo',engine='crusoe',speed=8))
        self.config.setdefault('models',{role:Adapter(self.config['engine'],role).model for role in ('planner','orchestrator','worker','retriever','verifier','treatment')})
        self.config.setdefault('provider_base',Adapter(self.config['engine']).base)
        # New Crusoe sessions pin their fallback before the first paid call.
        # Restores use saved configuration, never newly introduced defaults.
        if self.config['engine']=='crusoe' and 'fallback' not in self.config:
            aliases={'nvidia/NVIDIA-Nemotron-3.5-Super-VL':'nvidia/nemotron-3.5-super-vl',
                     'nvidia/NVIDIA-Nemotron-3-Super-120B-A12B':'nvidia/nemotron-3-super-120b-a12b',
                     'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B':'nvidia/nemotron-3-nano-30b-a3b',
                     'nvidia/Nemotron-3-Nano-Omni-Reasoning-30B-A3B':'nvidia/nemotron-3.5-super-vl'}
            self.config['fallback']=dict(after_failures=2,engine='gemma',provider_base=Adapter('gemma').base,
                models={role:aliases.get(model,model) for role,model in self.config['models'].items()})
        self.config.setdefault('trial',getattr(self.world,'trial',None))
        self.provider_routes={}
        self.committed=0; self.epoch=0; self.persisted=False; self.storage_error=None; self.pending=None
        self.telemetry=Telemetry(); self.controller=DemoController(); self.executor=concurrent.futures.ThreadPoolExecutor(max_workers=7)
        self.futures={}; self.requests={}; self.inference=[]; self.failures={}; self.retry_after={}; self.waiting=None; self.closed=False; self.last_commit=0; self.active_wall=0
        self.thread=threading.Thread(target=self.loop,daemon=True); self.thread.start()

    def persist(self):
        try:
            self.world.runtime_state=dict(config=self.config,inference=self.inference,failures=self.failures,provider_routes=self.provider_routes,active_wall=self.active_wall,pending_requests=self.requests)
            if not self.persisted:
                lease=self.repository.create(self.world,self.config); self.epoch=lease['resume_epoch']; self.persisted=True
            if self.persisted and self.last_commit and time.monotonic()-self.last_commit>15:
                self.repository.lease(self.world.id)
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
            if self.storage_error: raise ValueError('storage_blocked; retry the pending batch first')
            if self.world.status in TERMINAL: return
            self.world.status=status; self.world.event(status)
            self.persist()

    def retry(self):
        with self.lock:
            # Renew the same writer lease; never overwrite another writer's session.
            if self.persisted: self.repository.lease(self.world.id)
            if self.persist():
                if self.world.status not in TERMINAL:self.world.status='paused'
                self.world.event('storage_recovered'); self.persist()

    def command(self,robot,action,args=None,command_id=None):
        with self.lock:
            if self.storage_error: raise ValueError('storage_blocked')
            receipt=self.world.command(command_id or uid(),robot,action,**(args or {}))
            self.persist() # Acceptance is durable before the next physical tick.
            return receipt

    def restore(self,session):
        with self.lock:
            if self.persisted and self.world.status=='running': raise ValueError('pause the current session before restoring another')
            self.collect_inactive_calls()
            if self.futures: raise ValueError('wait for outstanding inference accounting before restoring')
            rows=self.repository.read('sessions',f'id=eq.{session}&limit=1')
            if not rows or (rows[0]['kind']=='fleet')!=(self.world.kind=='fleet'): raise ValueError('session belongs to a different runtime family')
            if rows[0].get('status') in TERMINAL: raise ValueError('terminal sessions are read-only; create a new session')
            config=copy.deepcopy(rows[0]['metadata']['configuration'])
            if config.get('treatment_code_hash'):
                from .common import treatment_implementation_hash
                if config['treatment_code_hash']!=treatment_implementation_hash():raise ValueError('saved treatment implementation changed; create a new session')
            if config.get('mode') in ('live','vision') and ('models' not in config or 'provider_base' not in config): raise ValueError('saved live session lacks exact model pins; create a new session')
            state=self.repository.restore(session); lease=self.repository.lease(session)
            from .treatment import Treatment
            from .care import PlantCare
            from .manipulation import Manipulation
            cls={'fleet':Mission,'irrigation':Treatment,'care':PlantCare,'arm':Manipulation}[rows[0]['kind']]
            self.world=cls.restore(state); self.world.status='paused'
            self.config=config
            durable_runtime=state.get('runtime_state',{})
            self.inference=durable_runtime.get('inference',[]);self.failures=durable_runtime.get('failures',{})
            self.provider_routes=durable_runtime.get('provider_routes',{})
            self.active_wall=durable_runtime.get('active_wall',0)
            self.requests={}
            for robot,request in durable_runtime.get('pending_requests',{}).items():
                unresolved=dict(id=uid(),request_id=request['id'],status='interrupted_unknown',usage={},cost=None)
                self.inference.append(unresolved)
                self.world.event('inference_interrupted',robot,request=request,result=unresolved)

            for _,future in self.futures.values(): future.cancel()
            self.futures={};self.waiting=None
            self.committed=lease['sequence']; self.epoch=lease['resume_epoch']; self.persisted=True
            self.pending=None; self.storage_error=None; self.telemetry=Telemetry()
            # Per-robot sequence resumes monotonically.
            for row in self.repository.read('robot_sessions',f'session_id=eq.{session}&limit=10'):
                self.telemetry.sequences[row['robot_id']]=row['sequence']
            self.world.event('restored',resume_epoch=self.epoch); self.persist()

    def adapter(self,role):
        config=self.config['fallback'] if self.provider_routes.get(role,{}).get('fallback') else self.config
        adapter=Adapter(config['engine'],role)
        adapter.model=config['models'][role];adapter.base=config['provider_base']
        return adapter

    def dispatch(self,robot,role,observation,image=None):
        if self.storage_error or self.world.status!='running': return False
        adapter=self.adapter(role)
        request=dict(id=uid(),session_id=self.world.id,role=role,model=adapter.model,
                     provider=getattr(adapter,'provider',self.config['engine']),provider_base=adapter.base,
                     fallback=bool(self.provider_routes.get(role,{}).get('fallback')),
                     prompt_version=self.world.prompt_versions.get(role),observation_hash=digest(observation),
                     input_event_sequence=self.world.seq,frame=copy.deepcopy(observation.get('frame')),
                     input_images=copy.deepcopy(observation.get('input_images',[])),scan_artifact_id=(observation.get('scan') or {}).get('artifact_id'),
                     telemetry_sequences={key:value.get('sequence') for key,value in self.telemetry.latest.items()},
                     image_hash=digest(image) if image else None)
        self.requests[robot]=request
        self.world.event('inference_requested',robot,request=request)
        if not self.persist(): return False
        prompt=getattr(self.world,'prompt_texts',{}).get(role,PROMPT)
        def call():
            try:
                result=adapter.call(observation,image,prompt);result['request_id']=request['id'];return result
            except InferenceError as exc:
                if not exc.metrics:exc.metrics=adapter.failed_metrics(time.monotonic())
                exc.metrics['request_id']=request['id'];raise
        self.futures[robot]=(self.world.id,self.executor.submit(call))
        return True

    def consume(self,robot,future):
        request=self.requests.pop(robot,None)
        try:
            result=future.result()
        except InferenceError as exc:
            if request and exc.metrics:
                exc.metrics.update(provider_base=request['provider_base'],fallback=request['fallback'])
            # Only transport/auth/protocol failures count. Rejected physical
            # actions and missed grasps are handled after this boundary.
            if request and exc.metrics and self.world.status=='running':
                role=request['role'];route=self.provider_routes.setdefault(role,dict(fallback=False,failures=0))
                if request['fallback']!=route['fallback']:
                    # An older Crusoe request can finish after another worker
                    # switched their shared role. It is still accounted, but
                    # cannot consume the new provider's failure budget.
                    exc.provider_failure_count=0
                    raise
                route['failures']+=1
                fallback=self.config.get('fallback')
                if fallback and not route['fallback'] and route['failures']>=fallback['after_failures']:
                    route.update(fallback=True,failures=0,reason=str(exc))
                    exc.fallback_activated=True
                    self.world.event('provider_fallback',robot,role=role,reason=str(exc),after_failures=fallback['after_failures'],
                        from_provider=request['provider'],from_model=request['model'],to_provider='gateway',to_model=fallback['models'][role])
                exc.provider_failure_count=route['failures']
            raise
        if request:
            role=request['role'];route=self.provider_routes.setdefault(role,dict(fallback=False,failures=0))
            if request['fallback']==route['fallback']:route['failures']=0
            result.update(provider_base=request['provider_base'],fallback=request['fallback'])
        return result

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
            if session!=self.world.id: continue
            if self.world.status!='running':
                self.collect_inactive_calls();return
            del self.futures[robot]
            try:
                result=self.consume(robot,future); self.inference.append(result)
                decision=result['decision']; args=decision['arguments']
                self.world.event('decision',robot,result=result,prompt_version=self.world.prompt_versions)
                if robot=='planner':
                    if decision['action']!='accept_contract': raise InferenceError('Planner must accept the fixed contract')
                    self.world.planned=True
                elif robot=='verifier':
                    if decision['action'] not in ('verify','claim_complete'): raise InferenceError('Verifier must evaluate the completion evidence')
                    self.world.command(uid(),'verifier','claim_complete')
                else:
                    receipt=self.world.command(uid(),robot,decision['action'],**args)
                    if not receipt['accepted']: raise InferenceError('Rejected model command: '+receipt['reason'])
                self.failures[robot]=0
                if not self.persist(): return
            except InferenceError as exc:
                if exc.metrics: self.inference.append(exc.metrics)
                self.failures[robot]=getattr(exc,'provider_failure_count',self.failures.get(robot,0)+1)
                self.world.event('inference_error',robot,error=str(exc))
                self.retry_after[robot]=time.monotonic()+min(8,2**self.failures[robot])
                if self.failures[robot]>=3: self.world.status='blocked'
                if not self.persist(): return
        if self.storage_error or self.world.status!='running': return
        obs=self.world.observations()
        obs['telemetry']=copy.deepcopy(self.telemetry.latest)
        # Deterministic feasible option enumeration constrains role calls, but does not choose for a model.
        if not getattr(self.world,'planned',False):
            if 'planner' not in self.futures and self.world.status=='running' and now>=self.retry_after.get('planner',0):
                self.dispatch('planner','planner',dict(role='contract planner',observation=obs,instruction='Use choose_action action accept_contract with arguments {} to pin this fixed valid contract. You cannot weaken coverage, reserve, deadlines or acceptance checks.'))
            return
        if all(self.world.verify().values()):
            if 'verifier' not in self.futures and self.world.status=='running' and now>=self.retry_after.get('verifier',0):
                self.dispatch('verifier','verifier',dict(role='independent verifier explanation',observation=obs,checks=self.world.verify(),instruction='Explain the independent checks concisely; use choose_action action verify with arguments {}. Code determines success.'))
            return
        candidates=self.controller.decisions(obs)
        grouped={}
        for robot,action,args in candidates: grouped.setdefault(robot,[]).append(dict(action=action,arguments=args))
        if all(self.world.verify().values()): grouped['orchestrator']=[dict(action='claim_complete',arguments={})]
        for robot,options in grouped.items():
            if robot in self.futures or self.world.status!='running' or now<self.retry_after.get(robot,0): continue
            role='orchestrator' if robot=='orchestrator' else 'retriever' if robot=='R1' else 'worker'
            permitted=dict(observation=obs,role=role,robot=robot,feasible_options=options)
            if not self.dispatch(robot,role,permitted): return

    def step(self,elapsed):
        if self.storage_error: return
        if self.config['mode']=='demo': self._demo()
        else: self._live()
        if self.storage_error or self.world.status!='running': return
        dt=min(elapsed,.5)*self.config.get('speed',8)
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
                    if self.world.status=='running':
                        self.active_wall+=elapsed
                        self.step(elapsed)
                    else: self.collect_inactive_calls()
                    if self.persisted and self.world.status not in TERMINAL and now-self.telemetry.last_heartbeat>=1:
                        waiting={robot:'inference_wait' for robot in self.futures} if self.world.kind=='fleet' else self.waiting
                        self.telemetry.sample(self.world,self.epoch,True,waiting)
                    if self.persisted and self.world.seq>self.committed and now-self.last_commit>=.5: self.persist()
                except (ValueError,StorageError,InferenceError) as exc:
                    if hasattr(self.world,'feedback'): self.world.feedback=str(exc)
                    self.world.status='blocked'; self.world.event('blocked',error=str(exc)); self.persist()
                except Exception:
                    self.world.status='blocked'; self.world.event('blocked',error='Internal runtime error; inspect server diagnostics'); self.persist()

    def snapshot(self):
        with self.lock:
            state=self.world.snapshot(); state['events']=state['events'][-100:]
            state.update(config=self.config,provider_routes=copy.deepcopy(self.provider_routes),storage=dict(healthy=not self.storage_error,error=self.storage_error,committed_sequence=self.committed),telemetry=self.telemetry.latest,
                         inference=dict(calls=len(self.inference),pending_calls=len(self.futures),latency_seconds=sum(r.get('latency',0) for r in self.inference),failed_calls=sum(r.get('status') in ('failed','interrupted_unknown') for r in self.inference),tokens=sum(r['usage'].get('total_tokens',0) for r in self.inference),cost=sum(r['cost'] for r in self.inference) if self.inference and all(r['cost'] is not None for r in self.inference) else None,results=self.inference[-30:]),waiting=self.waiting)
            if self.storage_error: state['status']='storage_blocked'
            return state

    def close(self):
        self.closed=True
        for _,future in list(self.futures.values()):
            future.cancel()
            future.add_done_callback(lambda _: self.collect_inactive_calls())
        self.executor.shutdown(wait=False,cancel_futures=True)
        if hasattr(self.repository,'close_current'): self.repository.close_current()

    def collect_inactive_calls(self):
        with self.lock:
            for robot,(session,future) in list(self.futures.items()):
                if not future.done(): continue
                del self.futures[robot]
                if session!=self.world.id or future.cancelled(): continue
                try: result=self.consume(robot,future)
                except InferenceError as exc: result=exc.metrics
                except Exception: result=None
                if result:
                    self.inference.append(result)
                    self.world.event('inference_discarded',robot,result=result,reason='Session paused, stopped or replaced; no action executed')
            if self.persisted and not self.storage_error and self.world.seq>self.committed:self.persist()
