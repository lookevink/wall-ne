"""Explicit new-session continuation; never rewrite a saved implementation identity."""
import copy
from .common import uid, implementation_hash, treatment_implementation_hash
from .fleet_care import FleetCareWorld,FleetCareRuntime
from .orchard_care import OrchardCare
from .runtime import gemini_care_fallback


def refresh_gemini_fallback(config,world):
    previous=config.get('fallback')
    if not previous or previous.get('engine')!='gemini':
        raise ValueError('fallback refresh requires an existing Gemini fallback')
    config['fallback']=gemini_care_fallback(previous['models'])
    world.event('fallback_policy_updated',previous=previous,current=config['fallback'])


def clone_world(saved,cls,source_id,reason,retain_damage=False):
    world=cls.restore(saved)
    if not world.verify().get('inventory'):raise ValueError('source inventory or contract integrity failed')
    if getattr(world,'damage',[]) and not retain_damage:raise ValueError('cannot continue a mission with recorded organism damage')
    pending=saved.get('runtime_state',{}).get('pending_requests',{})
    if pending:raise ValueError('wait for source inference accounting before continuing')
    world.id=uid();world.seq=0;world.events=[];world.status='paused';world.revision+=1
    world.continuation_source=dict(session_id=source_id,reason=reason,implementation_hash=saved.get('runtime_state',{}).get('config',{}).get('treatment_code_hash'))
    for name in ('runtime_state','prompt_texts'):
        world.__dict__.pop(name,None)
    world.prompt_versions={'orchestrator':'fleet-care-v1'} if isinstance(world,FleetCareWorld) else {'treatment':'treatment-v1'}
    if isinstance(world,OrchardCare):
        world.frame=None;world.frame_request=None;world.depth_request=None;world.alignment=None;world.contact_ack=None;world.crown_projection=None
        world.feedback='Controller updated with saved physical state. Inspect the fresh image and current_grasp_step before acting.'
    world.event('continued',source=world.continuation_source)
    return world


def continue_fleet(repository,source_id,reason,refresh_fallback=False,interrupted=False):
    from .background_storage import ensure_cloud_restore_safe,local_restart_checkpoint
    if not interrupted:ensure_cloud_restore_safe()
    restore=(lambda sid:local_restart_checkpoint(repository,sid)) if interrupted else repository.restore
    if type(refresh_fallback) is not bool:raise ValueError('refresh_fallback must be boolean')
    saved=restore(source_id)
    if saved.get('mission_type')!='fleet_care' or (saved['status']=='running' and not interrupted):raise ValueError('continue a paused or terminal fleet-care session only')
    world=clone_world(saved,FleetCareWorld,source_id,reason)
    state=saved.get('runtime_state',{});config=copy.deepcopy(state['config'])
    config.pop('prompt_version',None)
    config.update(code_hash=implementation_hash(),treatment_code_hash=treatment_implementation_hash(),continuation_source=source_id)
    if refresh_fallback:refresh_gemini_fallback(config,world)
    sources={}
    for index,assignment in world.assignments.items():
        sid=assignment.get('session_id')
        if not sid:continue
        source=restore(sid);worker_world=OrchardCare.restore(source)
        if source['status']=='running' and not interrupted:raise ValueError('stop the source worker before continuing')
        if worker_world.tasks!=[world.tasks[int(index)]] or worker_world.robot['id']!=assignment['vehicle']:raise ValueError('source worker assignment integrity failed')
        worker_state=source.get('runtime_state',{})
        if worker_state.get('pending_requests'):raise ValueError('wait for worker inference accounting before continuing')
        clone=clone_world(source,OrchardCare,sid,reason,retain_damage=interrupted)
        if refresh_fallback and source['status']!='completed':
            # Validate every worker policy before creating any new session.
            worker_state=copy.deepcopy(worker_state)
            refresh_gemini_fallback(worker_state['config'],clone)
        sources[index]=(source,worker_world,worker_state,clone)
    runtime=FleetCareRuntime(world,repository,config)
    runtime.active_wall=state.get('active_wall',0);runtime.inference=copy.deepcopy(state.get('inference',[]));runtime.provider_routes=copy.deepcopy(state.get('provider_routes',{}))
    try:
        with runtime.lock:
            for index,assignment in world.assignments.items():
                sid=assignment.get('session_id')
                if not sid:assignment['status']='reserved';continue
                source,worker_world,worker_state,clone=sources[index]
                if source['status']=='completed' or assignment['status']=='requires_review':
                    assignment['status']='completed' if source['status']=='completed' else 'requires_review'
                    world.results[sid]=dict(status=source['status'],checks=worker_world.verify(),worker=assignment['vehicle'],completed_trees=worker_world.completed_trees,inference=worker_state.get('inference',[]),exception=copy.deepcopy(getattr(worker_world,'task_exception',None)),outcome=worker_world.tree_outcome())
                    world.vehicles[assignment['vehicle']]=copy.deepcopy(worker_world.robot)
                    continue
                child=runtime.make_child(int(index),assignment['vehicle'])
                runtime.children[assignment['vehicle']]=child
                child.world=clone
                child.world.wall_limit=world.contract['wall_limit'];child.world.cost_limit=world.contract['cost_limit']
                child.config=copy.deepcopy(worker_state['config'])
                child.config.pop('prompt_version',None)
                child.config.update(code_hash=implementation_hash(),treatment_code_hash=treatment_implementation_hash(),parent_session_id=world.id,task_index=int(index),continuation_source=sid)
                child.active_wall=worker_state.get('active_wall',0);child.inference=copy.deepcopy(worker_state.get('inference',[]));child.provider_routes=copy.deepcopy(worker_state.get('provider_routes',{}))
                with child.lock:
                    if not child.persist():raise ValueError('continued worker checkpoint could not be committed')
                runtime.children[assignment['vehicle']]=child
                if sid in world.results:
                    world.__dict__.setdefault('superseded_results',{})[sid]=world.results.pop(sid)
                assignment.update(session_id=child.world.id,status='assigned')
                world.worker_sessions[child.world.id]=dict(task_index=int(index),worker=assignment['vehicle'],continuation_source=sid)
                world.vehicles[assignment['vehicle']]=copy.deepcopy(child.world.robot)
            world.feedback='Saved care and physical poses preserved; updated controller ready to continue'
            if not runtime.persist():raise ValueError('continued fleet checkpoint could not be committed')
        return runtime
    except Exception:
        runtime.close();raise
