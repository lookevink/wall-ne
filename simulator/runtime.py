"""One writer per session, persistence barriers, wall clock and role-call executor."""
import concurrent.futures
import os
import copy
import threading
import time
from .common import uid,digest,utc
from .engine import Mission,TERMINAL
from .agents import DemoController
from .persistence import Repository,StorageError
from .telemetry import Telemetry
from .inference import Adapter,InferenceError,PROMPT,build_request

def gemini_care_fallback(models):
    adapter=Adapter('gemini','treatment')
    return dict(after_failures=1,engine='gemini',provider_base=adapter.base,inference_timeout=30,max_tokens=2048,
                models={**models,'treatment':adapter.model})

class Runtime:
    def __init__(self,world=None,repository=None,config=None):
        from .background_storage import BackgroundRepository
        if isinstance(repository,BackgroundRepository):repository=repository.remote
        self.lock=threading.RLock(); self.world=world or Mission(); self.repository=Repository(repository.url,repository.key) if isinstance(repository,Repository) else repository or Repository()
        self.config=copy.deepcopy(config or dict(mode='demo',engine='crusoe',speed=8))
        if getattr(self.world,'mission_type',None) in ('fleet_care','full_care'):
            self.config['care_controller']='ultra_fast'
        self.config.setdefault('models',{role:Adapter(self.config['engine'],role).model for role in ('planner','orchestrator','worker','retriever','verifier','treatment')})
        self.config.setdefault('provider_base',Adapter(self.config['engine']).base)
        # New Crusoe sessions pin their fallback before the first paid call.
        # Restores use saved configuration, never newly introduced defaults.
        if self.config['engine']=='crusoe' and 'fallback' not in self.config:
            aliases={'nvidia/NVIDIA-Nemotron-3.5-Super-VL':'nvidia/nemotron-3.5-super-vl',
                         'nvidia/NVIDIA-Nemotron-3-Super-120B-A12B':'nvidia/nemotron-3-super-120b-a12b',
                         'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B':'nvidia/nemotron-3-nano-30b-a3b',
                         'nvidia/Nemotron-3-Nano-Omni-Reasoning-30B-A3B':'nvidia/nemotron-3.5-super-vl'}
            models={role:aliases.get(model,model) for role,model in self.config['models'].items()}
            # Both care controllers recover immediately from provider failures.
            # Children inherit this pinned policy; saved/explicit policies stay intact.
            if getattr(self.world,'mission_type',None) in ('fleet_care','full_care') or self.config.get('care_controller')=='ultra_fast':
                self.config['fallback']=gemini_care_fallback(models)
            elif os.getenv('WALLNE_GATEWAY_FALLBACK','0')=='1':
                self.config['fallback']=dict(after_failures=2,engine='gemma',provider_base=Adapter('gemma').base,
                    models=models)
            else:self.config['fallback']=None
        if self.config.get('care_controller')=='ultra_fast':
            self.config.setdefault('inference_timeout',6)
            self.config.setdefault('max_tokens',512)
        if self.config.get('care_controller')=='ultra_fast' and isinstance(self.repository,Repository):
            self.repository=BackgroundRepository(self.repository)
        self.config.setdefault('trial',getattr(self.world,'trial',None))
        self.config.setdefault('capture_training_inputs',True)
        self.provider_routes={}
        self.committed=0; self.epoch=0; self.persisted=False; self.storage_error=None; self.pending=None
        self.telemetry=Telemetry(); self.controller=DemoController(); self.executor=concurrent.futures.ThreadPoolExecutor(max_workers=7)
        self.futures={}; self.requests={}; self.inference=[]; self.failures={}; self.retry_after={}; self.waiting=None; self.closed=False; self.last_commit=0; self.active_wall=0
        self.query_answers={}; self.query_streak={}; self.incident_alert=False; self.escalation=None; self.offered={}
        self.thread=threading.Thread(target=self.loop,daemon=True); self.thread.start()

    def monitor(self,now):
        # Health and incidents are computed by code from heartbeats; a model only reads them and records a response.
        health=self.telemetry.health(now,self.failures)
        opened,resolved=self.telemetry.detect_incidents(self.world,health,self.storage_error)
        if opened and self.config['mode']=='live': self.incident_alert=True
        return health

    def persist(self):
        try:
            self.world.runtime_state=dict(config=self.config,inference=self.inference,failures=self.failures,provider_routes=self.provider_routes,active_wall=self.active_wall,pending_requests=self.requests)
            if not self.persisted:
                lease=self.repository.create(self.world,self.config); self.epoch=lease['resume_epoch']; self.persisted=True
            if self.persisted and self.last_commit and time.monotonic()-self.last_commit>15:
                self.repository.lease(self.world.id)
            if self.pending is None:
                self.world.event('checkpoint',status=self.world.status)
                artifacts=self.telemetry.flush(self.repository,self.world,self.executor if self.config.get('care_controller')=='ultra_fast' else None)
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
            if action=='stop' and receipt['accepted']:self.world.operator_stopped=True
            self.persist() # Acceptance is durable before the next physical tick.
            return receipt

    def restore(self,session):
        from .background_storage import ensure_cloud_restore_safe
        ensure_cloud_restore_safe()
        with self.lock:
            if self.persisted and self.world.status=='running': raise ValueError('pause the current session before restoring another')
            self.collect_inactive_calls()
            if self.futures: raise ValueError('wait for outstanding inference accounting before restoring')
            rows=self.repository.read('sessions',f'id=eq.{session}&limit=1')
            if not rows or (rows[0]['kind']=='fleet')!=(self.world.kind=='fleet'): raise ValueError('session belongs to a different runtime family')
            if rows[0].get('status') in TERMINAL: raise ValueError('terminal sessions are read-only; create a new session')
            config=copy.deepcopy(rows[0]['metadata']['configuration'])
            if config.get('arena')!=self.config.get('arena'):raise ValueError('saved mission belongs to a different arena')
            if config.get('treatment_code_hash'):
                from .common import treatment_implementation_hash
                if config['treatment_code_hash']!=treatment_implementation_hash():raise ValueError('saved treatment implementation changed; create a new session')
            if config.get('mode') in ('live','vision') and ('models' not in config or 'provider_base' not in config): raise ValueError('saved live session lacks exact model pins; create a new session')
            if config.get('care_controller')=='ultra_fast':
                from .background_storage import bind_for_restore
                self.repository=bind_for_restore(self.repository,session)
            else:
                from .background_storage import BackgroundRepository
                if isinstance(self.repository,BackgroundRepository):self.repository=Repository(self.repository.url,self.repository.key)
            state=self.repository.restore(session)
            if state.get('mission_type') in ('fleet_care','full_care') and config.get('care_controller')!='ultra_fast':
                raise ValueError('saved full-care session uses retired Standard control; start a new Ultra Fast session')
            lease=self.repository.lease(session)
            from .treatment import Treatment
            from .care import PlantCare
            from .manipulation import Manipulation
            cls={'fleet':Mission,'irrigation':Treatment,'care':PlantCare,'arm':Manipulation}[rows[0]['kind']]
            if state.get('arena')=='orchard':
                from .orchard_manipulation import OrchardManipulation
                from .orchard_care import OrchardCare
                from .fleet_care import FleetCareWorld
                cls=FleetCareWorld if state.get('mission_type')=='fleet_care' else OrchardCare if state.get('mission_type')=='full_care' else OrchardManipulation
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
        timeout=config.get('inference_timeout',self.config.get('inference_timeout'))
        if timeout is not None:adapter.timeout=timeout
        max_tokens=config.get('max_tokens',self.config.get('max_tokens'))
        if max_tokens is not None:adapter.max_tokens=max_tokens
        return adapter

    def dispatch(self,robot,role,observation,image=None):
        if self.storage_error or self.world.status!='running': return False
        adapter=self.adapter(role)
        observation=copy.deepcopy(observation);image=copy.deepcopy(image)
        prompt=getattr(self.world,'prompt_texts',{}).get(role,PROMPT)
        request=dict(id=uid(),session_id=self.world.id,role=role,model=adapter.model,
                     provider=getattr(adapter,'provider',self.config['engine']),provider_base=adapter.base,
                     fallback=bool(self.provider_routes.get(role,{}).get('fallback')),
                     prompt_version=self.world.prompt_versions.get(role),observation_hash=digest(observation),
                     input_event_sequence=self.world.seq,frame=copy.deepcopy(observation.get('frame')),
                     input_images=copy.deepcopy(observation.get('input_images',[])),scan_artifact_id=(observation.get('scan') or {}).get('artifact_id'),
                     telemetry_sequences={key:value.get('sequence') for key,value in self.telemetry.latest.items()},
                     image_hash=digest(image) if image else None)
        if self.config.get('capture_training_inputs',False):
            payload=dict(schema_version=1,request_id=request['id'],observation=observation,
                         body=build_request(observation,image,prompt,adapter.model,max_tokens=getattr(adapter,'max_tokens',None),provider=request['provider']))
            try:
                artifact=self.repository.artifact(self.world.id,robot,'policy_input',payload,
                    dict(request_id=request['id'],role=role,observation_hash=request['observation_hash']))
            except StorageError as exc:
                self.storage_error=str(exc);self.waiting='storage_blocked';return False
            self.pending_artifacts=getattr(self,'pending_artifacts',[])+[artifact]
            request['policy_input_artifact_id']=artifact['id']
            request['policy_input_hash']=digest(payload)
        self.requests[robot]=request
        self.world.event('inference_requested',robot,request=request)
        if not self.persist(): return False
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
                elif decision['action']=='query_telemetry' or decision['action']=='respond_incident' or decision['action'].startswith('incident_'):
                    # incident_<decision> options carry the decision in the action name; the rationale serves as the reason when none is given.
                    if decision['action']!='query_telemetry':
                        args=dict(args,decision=args.get('decision') or decision['action'].partition('_')[2],reason=args.get('reason') or decision.get('rationale') or '')
                    self.orchestrator_tool(robot,'query_telemetry' if decision['action']=='query_telemetry' else 'respond_incident',args)
                else:
                    self.query_streak[robot]=0
                    args=self.complete_arguments(robot,decision)
                    try: receipt=self.world.command(uid(),robot,decision['action'],**args)
                    except TypeError: raise InferenceError('Rejected model command: invalid argument names') from None
                    self.telemetry.note_command(robot,receipt['accepted'])
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
        obs['fleet_health']=self.telemetry.health(now,self.failures)
        obs['open_incidents']=copy.deepcopy(list(self.telemetry.incidents.values()))
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
        # A new incident engages the orchestrator even when the rule-based enumeration has nothing for it to assign.
        if self.incident_alert: grouped.setdefault('orchestrator',[])
        if 'orchestrator' in grouped:
            # One concrete option per incident and decision, so the choice is an enumerated action rather than a free-form argument.
            for incident in obs['open_incidents'][:2]:
                for choice in ('continue','retrieve','reassign','stop','escalate'):
                    grouped['orchestrator'].append(dict(action='incident_'+choice,arguments=dict(incident_id=incident['id'],incident_robot=incident['robot'])))
            grouped['orchestrator'].append(dict(action='query_telemetry',arguments=dict(robot='W1',since_sim_time=round(max(0,self.world.time-60),1))))
        for robot,options in grouped.items():
            if robot in self.futures or self.world.status!='running' or now<self.retry_after.get(robot,0): continue
            role='orchestrator' if robot=='orchestrator' else 'retriever' if robot=='R1' else 'worker'
            permitted=dict(observation=obs,role=role,robot=robot,feasible_options=options)
            if robot in self.query_answers: permitted['telemetry_query_result']=self.query_answers.pop(robot)
            if robot=='orchestrator': self.incident_alert=False
            self.offered[robot]=copy.deepcopy(options)
            if not self.dispatch(robot,role,permitted): return

    def complete_arguments(self,robot,decision):
        """A role picks one offered option: fields it left out are copied from that option, fields the option never had are dropped, and nothing is invented when the choice is ambiguous."""
        args={k:v for k,v in decision['arguments'].items() if k not in ('robot','decision','reason','action','command_id')}
        offered=[o for o in getattr(self,'offered',{}).get(robot,[]) if o['action']==decision['action']]
        if not offered: return args
        matches=[o for o in offered if all(o['arguments'].get(k)==v for k,v in args.items() if k in o['arguments'])]
        if len(matches)==1: return {**matches[0]['arguments'],**{k:v for k,v in args.items() if k in matches[0]['arguments']}}
        known=set().union(*(o['arguments'].keys() for o in offered))
        return {k:v for k,v in args.items() if k in known}

    def orchestrator_tool(self,robot,action,args):
        """Non-physical orchestrator tools: a bounded telemetry query answered by code, and a recorded incident decision."""
        if robot!='orchestrator': raise InferenceError(f'{action} is an orchestrator tool')
        try:
            if action=='query_telemetry':
                self.query_streak[robot]=self.query_streak.get(robot,0)+1
                if self.query_streak[robot]>3: raise ValueError('repeated telemetry queries without a physical decision')
                answer=self.telemetry.query(str(args.get('robot','')),float(args.get('since_sim_time') or 0))
                answer['queries_before_decision']=f"{self.query_streak[robot]} of 3; choose a physical option or an incident_* decision next"
                self.query_answers[robot]=answer
                self.world.event('telemetry_query',robot,arguments=args,samples=answer['samples'],returned=answer['returned'])
            else:
                choice=args.get('decision'); reason=args.get('reason','')
                if choice not in ('continue','retrieve','reassign','stop','escalate') or not isinstance(reason,str) or not 1<=len(reason)<=600: raise ValueError('respond_incident needs decision continue|retrieve|reassign|stop|escalate and a reason of 1..600 characters')
                incident_id=args.get('incident_id')
                if not incident_id:
                    # An omitted id is resolved only when it is unambiguous: a named robot with one open incident, or a single open incident.
                    import re
                    named=args.get('incident_robot') or args.get('target') or args.get('robot') or args.get('vehicle')
                    candidates=[i for i in self.telemetry.incidents.values() if not named or i['robot']==named]
                    if len(candidates)!=1:
                        # Models often put the helper vehicle in `target`; the robot the reason talks about is the incident's.
                        candidates=[i for i in self.telemetry.incidents.values() if re.search(r'\b'+re.escape(i['robot'])+r'\b',reason)]
                    if len(candidates)!=1: raise ValueError('respond_incident needs incident_id; open incidents: '+', '.join(f"{i['id']} ({i['robot']} {i['kind']})" for i in self.telemetry.incidents.values()))
                    incident_id=candidates[0]['id']
                incident=self.telemetry.respond(str(incident_id),choice,reason)
                self.query_streak[robot]=0
                self.world.event('incident_response',robot,incident_id=incident['id'],incident_kind=incident['kind'],target=incident['robot'],decision=choice,reason=reason)
                if choice=='stop': self.world.status='aborted'; self.world.event('aborted',robot,reason=reason)
                elif choice=='escalate':
                    # The robot is asking for a human: physical time pauses until an operator resumes.
                    self.escalation=dict(incident_id=incident['id'],robot=incident['robot'],reason=reason,wall_utc=utc())
                    self.world.status='paused'; self.world.event('escalation',robot,incident_id=incident['id'],target=incident['robot'],reason=reason)
        except (ValueError,TypeError) as exc: raise InferenceError(str(exc)) from None

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
                        self.monitor(now)
                    if self.persisted and self.world.seq>self.committed and now-self.last_commit>=(2 if self.config.get('care_controller')=='ultra_fast' else .5): self.persist()
                except (ValueError,StorageError,InferenceError) as exc:
                    if hasattr(self.world,'feedback'): self.world.feedback=str(exc)
                    self.world.status='blocked'; self.world.event('blocked',error=str(exc)); self.persist()
                except Exception:
                    # The operator-facing event stays generic; the traceback goes to the server's stderr.
                    import traceback; traceback.print_exc()
                    self.world.status='blocked'; self.world.event('blocked',error='Internal runtime error; inspect server diagnostics'); self.persist()

    def snapshot(self):
        with self.lock:
            # Heartbeats live in `telemetry`; keeping them out of the event window leaves room for the decisions and incidents the UI tickers show.
            state=self.world.snapshot(); state['events']=[e for e in state['events'] if e['type']!='heartbeat'][-100:]
            # Each robot also keeps its own short ticker, so a disabled worker's breakdown stays visible after the shared window moves on.
            ticker={}
            for e in reversed(self.world.events):
                robot=e.get('robot_id')
                if not robot or e['type'] in ('heartbeat','checkpoint','inference_requested','capture_requested','observation'): continue
                rows=ticker.setdefault(robot,[])
                if len(rows)<10: rows.append(e)
            state['robot_events']={robot:list(reversed(rows)) for robot,rows in ticker.items()}
            state.update(storage_timing=copy.deepcopy(getattr(self.repository,'timings',{})),config=self.config,provider_routes=copy.deepcopy(self.provider_routes),storage=dict(healthy=not self.storage_error,error=self.storage_error,committed_sequence=self.committed),telemetry=self.telemetry.latest,
                         health=self.telemetry.health(time.monotonic(),self.failures),incidents=dict(open=copy.deepcopy(list(self.telemetry.incidents.values())),recent=copy.deepcopy(self.telemetry.closed[-10:])),escalation=copy.deepcopy(self.escalation),
                         inference=dict(calls=len(self.inference),pending_calls=len(self.futures),latency_seconds=sum(r.get('latency',0) for r in self.inference),failed_calls=sum(r.get('status') in ('failed','interrupted_unknown') for r in self.inference),tokens=sum(r['usage'].get('total_tokens',0) for r in self.inference),cost=sum(r['cost'] for r in self.inference) if self.inference and all(r['cost'] is not None for r in self.inference) else None,results=self.inference[-30:]),waiting=self.waiting)
            if hasattr(self.repository,'status'):
                sync=self.repository.status();state['storage'].update(sync=sync,committed_sequence=sync['cloud_committed_sequence'],local_sequence=self.committed)
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
