"""Live fleet orchestration with durable, independently verified worker sessions."""
import copy
import time
import threading
from .engine import Mission, TERMINAL
from .runtime import Runtime
from .treatment_runtime import TreatmentRuntime
from .orchard_care import OrchardCare
from .common import digest, uid, treatment_implementation_hash
from .inference import InferenceError

ORCHESTRATION='''You orchestrate Wall-ne's five equipped orchard workers W1-W5. Mobilize every worker, including W5. Assign ten distinct trees for complete care. Choose one feasible option using choose_action: assign with row (task index) and vehicle, or claim_complete with {} after all independent checks pass. Workers execute live visual inspection, watering, fertilizer, pest removal and articulated weed extraction, then service at their docks. Each tree has exactly one owner; never duplicate active assignments. Prefer idle workers that have not yet participated, then assign remaining trees to available workers. Traffic reservations are enforced by the runtime. A blocked worker is an incident, never a completed tree. Continue assigning remaining trees to healthy available workers; failed workers remain unavailable for this run. R1 is the recovery vehicle, not a fitted plant-care worker. Do not instruct workers with hidden target coordinates.'''


class FleetCareWorld(Mission):
    def __init__(self,seed=7,tree_count=10):
        super().__init__(seed)
        self.arena='orchard';self.mission_type='fleet_care';self.phase='orchestration'
        self.tasks=OrchardCare(seed,tree_count).tasks;self.task_inventory_hash=digest(self.tasks)
        self.zones={};self.assignments={};self.worker_sessions={};self.results={}
        self.vehicles['W5']['lifecycle']='idle'
        self.contract=dict(goal=f'All five workers: fully care for {tree_count} orchard trees, collect weeds and return to docks',tree_count=tree_count,reserve=25,wall_limit=5400,cost_limit=10)
        self.contract_hash=digest(self.contract);self.feedback='Orchestrator ready to mobilize all five workers'
        self.prompt_versions={'orchestrator':'fleet-care-v1'}

    def options(self):
        busy={a['vehicle'] for a in self.assignments.values() if a['status']!='completed'}
        unused={v for v in self.vehicles if v.startswith('W') and not any(a['vehicle']==v for a in self.assignments.values())}
        available=[v for v in self.vehicles if v.startswith('W') and v not in busy and (not unused or v in unused)]
        return [dict(action='assign',arguments=dict(row=i,vehicle=v)) for i in range(len(self.tasks)) if str(i) not in self.assignments for v in available]

    def command(self,command_id,robot,action,**args):
        if command_id in self.receipts:return copy.deepcopy(self.receipts[command_id])
        receipt=dict(command_id=command_id,robot_id=robot,action=action,arguments=args,accepted=False,revision=self.revision)
        try:
            if self.status!='running':raise ValueError('mission not running')
            if robot!='orchestrator':raise ValueError('orchestrator only')
            if action=='assign':
                if dict(action=action,arguments=args) not in self.options():raise ValueError('assignment unavailable or already owned')
                i=args['row'];v=args['vehicle'];self.assignments[str(i)]=dict(vehicle=v,status='reserved',session_id=None)
                self.feedback=f'Orchestrator assigned tree {i+1} to {v}'
            elif action=='claim_complete':
                if not all(self.verify().values()):raise ValueError('independent fleet checks reject completion')
                self.status='completed';self.feedback=f'All {len(self.tasks)} trees fully cared for by five workers; fleet returned'
            else:raise ValueError('unknown orchestration action')
            receipt['accepted']=True;self.revision+=1
        except ValueError as exc:receipt['reason']=str(exc);self.feedback=str(exc)
        self.receipts[command_id]=receipt;self.event('accepted' if receipt['accepted'] else 'rejected',robot,receipt=receipt)
        return copy.deepcopy(receipt)

    def observations(self):
        return dict(mission=self.contract,vehicles=copy.deepcopy(self.vehicles),tasks=[dict(index=i,tree=t['tree']) for i,t in enumerate(self.tasks)],assignments=self.assignments,checks=self.verify(),instruction=ORCHESTRATION,feasible_options=self.options(),feedback=self.feedback)

    def verify(self):
        if not hasattr(self,'tasks'):return {}
        complete=len(self.results)==len(self.tasks) and all(r['status']=='completed' and all(r['checks'].values()) for r in self.results.values())
        return dict(trees_complete=complete,all_workers_used={a['vehicle'] for a in self.assignments.values()}=={'W1','W2','W3','W4','W5'},
                    care_verified=complete,returned=complete and all(v['position']==v['home'] and v['action'] is None for v in self.vehicles.values()),
                    reserve=all(v['minimum_battery']>25 for v in self.vehicles.values()),inventory=digest(self.tasks)==self.task_inventory_hash and digest(self.contract)==self.contract_hash)

    def snapshot(self):
        state=self.checkpoint();state['checks']=self.verify();return state


class FleetCareRuntime(Runtime):
    def __init__(self,world=None,repository=None,config=None):
        self.children={};self.navigation_owner=None;self.orchestrator_invalid=0
        super().__init__(world or FleetCareWorld(),repository,config)

    def persist(self):
        okay=super().persist()
        if not okay or self.world.status!='running':
            for child in self.children.values():
                with child.lock:
                    if child.world.status=='running':
                        child.world.status='paused'
                        child.world.event('parent_barrier',reason=self.storage_error or self.world.status)
                        child.persist()
        return okay

    def start(self):
        super().start()
        if self.storage_error:return
        for child in self.children.values():
            if child.world.status=='paused':child.start()

    def pause(self,status='paused'):
        super().pause(status)

    def close(self):
        for child in self.children.values():child.close()
        super().close()

    def restore(self,session):
        # Validate and acquire the destination before disturbing existing children.
        previous=self.children
        super().restore(session)
        for child in previous.values():child.close()
        self.children={}
        for i,a in self.world.assignments.items():
            if a['status']=='completed' or not a.get('session_id'):continue
            rows=self.repository.read('sessions',f'id=eq.{a["session_id"]}&limit=1')
            if rows and rows[0]['status'] in TERMINAL:
                saved=self.repository.restore(a['session_id']);w=OrchardCare.restore(saved)
                a['status']=w.status
                self.world.results[w.id]=dict(status=w.status,checks=w.verify(),worker=a['vehicle'],completed_trees=w.completed_trees,inference=saved.get('runtime_state',{}).get('inference',[]))
                self.world.vehicles[a['vehicle']]=copy.deepcopy(w.robot)
                if w.status!='completed':self.world.status='blocked';self.world.feedback=f'{a["vehicle"]}: saved worker outcome {w.status}'
                continue
            child=self.make_child(int(i),a['vehicle']);child.restore(a['session_id']);self.children[a['vehicle']]=child
        self.persist()

    def make_child(self,index,worker):
        world=OrchardCare(self.world.seed+index,1,worker,self.world.tasks[index])
        world.wall_limit=900;world.cost_limit=1
        world.robot['minimum_battery']=self.world.vehicles[worker]['minimum_battery']
        config={k:copy.deepcopy(v) for k,v in self.config.items() if k not in ('prompt_version','trial')}
        config.update(mode='vision',arena='orchard',parent_session_id=self.world.id,task_index=index,treatment_code_hash=treatment_implementation_hash())
        child=TreatmentRuntime(world,self.repository,config);child.navigation_gate=threading.Event()
        return child

    def launch_reserved(self):
        for i,a in self.world.assignments.items():
            if a['status']!='reserved':continue
            child=self.make_child(int(i),a['vehicle'])
            # Persist the child and the parent link before enabling any paid call.
            with child.lock:
                if not child.persist():
                    child.close();raise ValueError('worker session persistence failed')
            a.update(session_id=child.world.id,status='assigned');self.world.worker_sessions[child.world.id]=dict(task_index=int(i),worker=a['vehicle'])
            old=self.children.get(a['vehicle'])
            if old:old.close()
            self.children[a['vehicle']]=child
            self.world.event('worker_dispatched',a['vehicle'],task_index=int(i),session_id=child.world.id)
            if not self.persist():return
            child.start()

    def accept_frame(self,body):return self.sensor_worker(body).accept_frame(body)
    def accept_depth(self,body):return self.sensor_worker(body).accept_depth(body)
    def sensor_worker(self,body):
        child=self.children.get(body.get('worker'))
        if not child or body.get('mission_id')!=child.world.id:raise ValueError('unknown worker sensor session')
        return child

    def step(self,elapsed):
        if self.active_wall>self.world.contract['wall_limit']:
            self.pause('blocked');self.world.feedback='Fleet wall budget exhausted';self.persist();return
        self.launch_reserved()
        if self.storage_error:return
        self.sync_workers()
        if self.world.status!='running':return
        settled=bool(self.world.assignments) and all(a['status'] in TERMINAL for a in self.world.assignments.values())
        if settled and not self.world.options() and not all(self.world.verify().values()):
            succeeded=sum(a['status']=='completed' for a in self.world.assignments.values())
            self.world.status='failed'
            self.world.feedback=f'Run finished: {succeeded}/{len(self.world.tasks)} trees fully cared for; {len(self.world.assignments)-succeeded} failed attempts; {len(self.world.tasks)-len(self.world.assignments)} unattempted. Results retained for the next improvement.'
            self.world.event('run_finished',successful=succeeded,attempted=len(self.world.assignments),total=len(self.world.tasks))
            self.persist();return
        self.coordinate_traffic()
        entry=self.futures.get('orchestrator')
        if entry:
            session,future=entry
            if not future.done():return
            del self.futures['orchestrator']
            try:
                result=self.consume('orchestrator',future);self.inference.append(result)
                self.world.event('decision','orchestrator',result=result)
                decision=result['decision'];receipt=self.world.command(uid(),'orchestrator',decision['action'],**decision['arguments'])
                self.orchestrator_invalid=0 if receipt['accepted'] else self.orchestrator_invalid+1
                if self.orchestrator_invalid>=3:raise ValueError('Three invalid orchestration decisions')
            except InferenceError as exc:
                if exc.metrics:self.inference.append(exc.metrics)
                count=getattr(exc,'provider_failure_count',1);self.retry_after['orchestrator']=time.monotonic()+2**count
                self.world.event('inference_error','orchestrator',error=str(exc))
                if count>=3:raise ValueError('Orchestrator provider failure budget exhausted')
            self.persist();return
        if time.monotonic()<self.retry_after.get('orchestrator',0):return
        options=self.world.options()
        if all(self.world.verify().values()):options=[dict(action='claim_complete',arguments={})]
        if options:
            obs=self.world.observations();obs['feasible_options']=options
            self.dispatch('orchestrator','orchestrator',obs)

    def sync_workers(self):
        self.world.time=self.active_wall
        total_cost=sum(r.get('cost') or 0 for r in self.inference)
        for worker,child in self.children.items():
            with child.lock:
                w=child.world;self.world.vehicles[worker]=copy.deepcopy(w.robot)
                assignment=next(a for a in self.world.assignments.values() if a.get('session_id')==w.id)
                total_cost+=sum(r.get('cost') or 0 for r in child.inference)
                if child.storage_error:
                    self.pause('blocked');self.world.feedback=f'{worker}: storage failure';self.persist();return
                if w.status in TERMINAL and assignment['status']!=w.status:
                    assignment['status']=w.status
                    self.world.results[w.id]=dict(status=w.status,checks=w.verify(),worker=worker,completed_trees=copy.deepcopy(w.completed_trees),inference=copy.deepcopy(child.inference))
                    self.world.event('worker_finished',worker,status=w.status,checks=w.verify(),session_id=w.id)
                    if w.status!='completed':
                        self.world.feedback=f'{worker} stopped: {w.feedback}. Healthy workers continue.'
                    self.persist()
        # Completed workers that have a newer assignment are counted from durable results.
        active={c.world.id for c in self.children.values()}
        total_cost+=sum(r.get('cost') or 0 for sid,result in self.world.results.items() if sid not in active for r in result['inference'])
        if total_cost>=self.world.contract['cost_limit']:
            self.pause('blocked');self.world.feedback='Fleet reported-cost cap';self.persist()

    def coordinate_traffic(self):
        if self.navigation_owner:
            owner=self.children.get(self.navigation_owner)
            if not owner or (owner.world.robot['action'] or {}).get('kind')!='navigate':self.navigation_owner=None
        for worker,child in self.children.items():
            if not self.navigation_owner and (child.world.robot['action'] or {}).get('kind')=='navigate':self.navigation_owner=worker
            if worker==self.navigation_owner:child.navigation_gate.set()
            else:child.navigation_gate.clear()

    def snapshot(self):
        with self.lock:
            state=super().snapshot();workers={worker:child.snapshot() for worker,child in self.children.items()}
            state['care_workers']=workers;state['navigation_owner']=self.navigation_owner
            for worker,s in workers.items():state['vehicles'][worker]=s['robot'];state['telemetry'].update(s['telemetry'])
            all_results=list(self.inference)
            active={s['id'] for s in workers.values()}
            for sid,result in self.world.results.items():
                if sid not in active:all_results+=result['inference']
            for child in self.children.values():all_results+=child.inference
            state['inference'].update(calls=len(all_results),pending_calls=len(self.futures)+sum(s['inference']['pending_calls'] for s in workers.values()),failed_calls=sum(r.get('status') in ('failed','interrupted_unknown') for r in all_results),tokens=sum(r.get('usage',{}).get('total_tokens',0) for r in all_results),cost=sum(r['cost'] for r in all_results) if all_results and all(r.get('cost') is not None for r in all_results) else None)
            inventory=dict(id=state['id'],seed=state['seed'],trial='precision',weeds=[],protected=[],pests=[],beneficial=[])
            for i,task in enumerate(self.world.tasks):
                a=self.world.assignments.get(str(i),{});child=workers.get(a.get('vehicle'))
                if child and child['id']==a.get('session_id'):
                    inventory['weeds'].append(child['weed']);inventory['pests']+=child['pests']
                else:
                    done=a.get('status')=='completed';inventory['weeds'].append(dict(task['weed'],removed=done));inventory['pests']+=[dict(p,removed=done) for p in task['pests']]
                inventory['protected']+=task['protected'];inventory['beneficial']+=task['beneficial']
            state['care_inventory']=inventory
            return state
