"""Sequenced health and sampled actual movement, independent of inference."""
import time
import copy
import math
from .common import utc,uid

UNITS=dict(coordinates='x right / y up / z toward rover',position='m',joints='deg',quaternion='xyzw',force='N',water='L',fertilizer='simulated g')
STALE_HEARTBEAT=5      # wall seconds without a heartbeat
STALL_SIM_SECONDS=20   # working with no physical progress
HISTORY=900            # heartbeats kept in memory per robot (15 minutes at 1 Hz)
PROGRESS_FIELDS=('position','lifecycle','action_id','water','joints','opening','force','holding','extracted','deposited')
QUERY_FIELDS=('sim_time','position','battery','water','lifecycle','waiting_reason','fault','action_id','task_id','last_progress_sim_time','joints','opening','force','load','holding','extracted','deposited')

class Telemetry:
    def __init__(self):
        self.sequences={}; self.last_heartbeat=0; self.started=time.monotonic()
        self.motion=[]; self.latest={}; self.history={}; self.incidents={}; self.closed=[]; self.rejections={}

    def robots(self,world):
        return world.vehicles if world.kind=='fleet' else {world.robot['id']:world.robot}

    def sample(self,world,epoch,heartbeat=False,waiting=None):
        now=time.monotonic()
        for key,v in self.robots(world).items():
            self.sequences[key]=self.sequences.get(key,0)+1
            envelope=dict(schema_version=1,session_id=world.id,robot_id=key,resume_epoch=epoch,sequence=self.sequences[key],wall_utc=utc(),elapsed=now-self.started,sim_time=world.time,revision=world.revision,prompt_version=world.prompt_versions,action_id=(v.get('action') or {}).get('id'),task_id=(v.get('action') or {}).get('zone'))
            reason=waiting.get(key) if isinstance(waiting,dict) else waiting
            health=dict(envelope,position=v['position'],battery=v['battery'],reserve=20,water=v.get('water'),lifecycle=v['lifecycle'],waiting_reason=reason if not v.get('action') else None,fault=v.get('fault'),last_progress_revision=world.revision)
            if world.kind=='arm':
                health.update(joints=world.joints,tool_pose=world.tool_pose(),opening=world.opening,force=world.force,contact=world.holding,load=world.load,holding=world.holding,extracted=world.extracted,deposited=world.deposited,collision=world.collision)
            previous=self.latest.get(key)
            changed=not previous or any(health.get(field)!=previous.get(field) for field in PROGRESS_FIELDS)
            health['last_progress_revision']=world.revision if changed else previous['last_progress_revision']
            health['last_progress_sim_time']=world.time if changed else previous.get('last_progress_sim_time',world.time)
            self.latest[key]=copy.deepcopy(health)
            if not heartbeat:self.motion.append(copy.deepcopy(health))
            if heartbeat:
                world.event('heartbeat',key,telemetry=copy.deepcopy(health))
                rows=self.history.setdefault(key,[]); rows.append(copy.deepcopy(health)); del rows[:-HISTORY]
        if heartbeat: self.last_heartbeat=now

    def flush(self,repo,world,executor=None):
        if not self.motion: return []
        chunks=[]
        # Never bridge gaps by inventing movement samples.
        current=[]; start=None
        for sample in self.motion:
            if start is None: start=sample['sim_time']
            if sample['sim_time']-start>2 and current:
                chunks.append(current); current=[]; start=sample['sim_time']
            current.append(sample)
        if current: chunks.append(current)
        def upload(chunk):
            return repo.artifact(world.id,None,'movement',chunk,dict(units=UNITS,start=chunk[0]['sim_time'],end=chunk[-1]['sim_time'],samples=len(chunk)))
        return list(executor.map(upload,chunks)) if executor and len(chunks)>1 else [upload(chunk) for chunk in chunks]

    def note_command(self,robot,accepted):
        # Consecutive rejections without an accepted command are the loop signal; physics progress resets nothing here.
        self.rejections[robot]=0 if accepted else self.rejections.get(robot,0)+1

    @staticmethod
    def health_status(heartbeat_age,waiting,failures_without_progress,lifecycle='idle',stalled=0):
        if lifecycle=='disabled': return 'disabled'
        if heartbeat_age>STALE_HEARTBEAT: return 'stale_heartbeat'
        if failures_without_progress>=3: return 'possible_loop'
        if stalled>STALL_SIM_SECONDS: return 'stalled'
        return 'healthy_wait' if waiting else 'healthy'

    def health(self,now=None,failures=None):
        """Code-computed health per robot from heartbeats. Models read it; nothing a model says can change it."""
        now=time.monotonic() if now is None else now; failures=failures or {}
        age=now-self.last_heartbeat if self.last_heartbeat else 0
        summary={}
        for robot,h in self.latest.items():
            working=h['lifecycle']=='working' and h.get('action_id')
            stalled=max(0,h['sim_time']-h.get('last_progress_sim_time',h['sim_time'])) if working else 0
            loops=max(failures.get(robot,0),self.rejections.get(robot,0))
            summary[robot]=dict(status=self.health_status(age,h.get('waiting_reason'),loops,h['lifecycle'],stalled),heartbeat_age=round(age,2),lifecycle=h['lifecycle'],action_id=h.get('action_id'),
                                waiting_reason=h.get('waiting_reason'),fault=h.get('fault'),battery=h['battery'],position=h['position'],stalled_sim_seconds=round(stalled,2),
                                failures_without_progress=loops,sequence=h['sequence'],open_incidents=[i['id'] for i in self.incidents.values() if i['robot']==robot])
        return summary

    def detect_incidents(self,world,health,storage_error=None):
        """Open one incident per (robot, kind) while its condition holds and close it when the condition clears: deduplicated, never re-emitted."""
        robots=self.robots(world); conditions={}
        for robot,h in health.items():
            v=robots.get(robot,{})
            if h['lifecycle']=='disabled' and not v.get('recovered'): conditions[(robot,'breakdown')]=f"{robot} disabled: {h.get('fault') or 'fault'}; retrieval required"
            if h['status']=='stale_heartbeat': conditions[(robot,'stale_heartbeat')]=f"no heartbeat for {h['heartbeat_age']} s"
            if h['status']=='possible_loop': conditions[(robot,'possible_loop')]=f"{h['failures_without_progress']} repeated failed attempts without progress"
            if h['status']=='stalled': conditions[(robot,'stalled')]=f"working with no physical progress for {h['stalled_sim_seconds']} simulated s"
        if storage_error: conditions[('storage','storage_blocked')]=storage_error
        opened=[]; resolved=[]
        for key,detail in conditions.items():
            if key in self.incidents: continue
            incident=dict(id=uid(),kind=key[1],robot=key[0],detail=detail,opened_sim_time=world.time,opened_wall=utc(),response=None)
            self.incidents[key]=incident; opened.append(incident)
            # Event payloads say incident_kind/incident_robot: `kind` and `robot` name the event itself.
            world.event('incident',key[0] if key[0] in robots else None,incident_kind=incident['kind'],incident_robot=incident['robot'],**{k:v for k,v in incident.items() if k not in ('kind','robot')})
        for key in [k for k in self.incidents if k not in conditions]:
            incident=self.incidents.pop(key); incident['resolved_sim_time']=world.time
            self.closed.append(incident); del self.closed[:-20]; resolved.append(incident)
            world.event('incident_resolved',key[0] if key[0] in robots else None,id=incident['id'],incident_kind=incident['kind'],incident_robot=incident['robot'],response=incident['response'])
        return opened,resolved

    def respond(self,incident_id,decision,reason,by='orchestrator'):
        incident=next((i for i in self.incidents.values() if i['id']==incident_id),None)
        if not incident: raise ValueError('unknown or already resolved incident')
        incident['response']=dict(decision=decision,reason=reason,by=by,wall_utc=utc())
        return incident

    def query(self,robot,since_sim_time=0,limit=60):
        """Bounded, code-answered heartbeat history: an orchestrator asks for a window, never receives every sample, and cannot write it."""
        rows=[h for h in self.history.get(robot,[]) if h['sim_time']>=since_sim_time]
        if not rows: return dict(robot=robot,since_sim_time=since_sim_time,samples=0,returned=0,rows=[],note='no heartbeats in range; the in-memory window covers this process lifetime only')
        step=max(1,-(-len(rows)//limit)); picked=rows[::step]
        if (len(rows)-1)%step: picked=(picked+[rows[-1]])[-limit:]   # the newest heartbeat is always part of the answer
        compact=[{k:(round(h[k],3) if isinstance(h[k],float) else h[k]) for k in QUERY_FIELDS if h.get(k) is not None} for h in picked]
        travelled=sum(math.dist(a['position'][:2],b['position'][:2]) for a,b in zip(rows,rows[1:]))
        return dict(robot=robot,since_sim_time=since_sim_time,samples=len(rows),returned=len(compact),first_sim_time=rows[0]['sim_time'],last_sim_time=rows[-1]['sim_time'],
                    battery_delta=round(rows[-1]['battery']-rows[0]['battery'],2),distance_travelled_m=round(travelled,2),lifecycles=sorted({h['lifecycle'] for h in rows}),
                    faults=sorted({h['fault'] for h in rows if h.get('fault')}),rows=compact,units=UNITS)
