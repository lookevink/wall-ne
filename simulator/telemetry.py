"""Sequenced health and sampled actual movement, independent of inference."""
import time
from .common import utc

UNITS=dict(coordinates='x right / y up / z toward rover',position='m',joints='deg',quaternion='xyzw',force='N',water='L',fertilizer='simulated g')

class Telemetry:
    def __init__(self):
        self.sequences={}; self.last_heartbeat=0; self.started=time.monotonic()
        self.motion=[]; self.latest={}; self.incidents=set()

    def robots(self,world):
        return world.vehicles if world.kind=='fleet' else {'T1':world.robot}

    def sample(self,world,epoch,heartbeat=False,waiting=None):
        now=time.monotonic()
        for key,v in self.robots(world).items():
            self.sequences[key]=self.sequences.get(key,0)+1
            envelope=dict(schema_version=1,session_id=world.id,robot_id=key,resume_epoch=epoch,sequence=self.sequences[key],wall_utc=utc(),elapsed=now-self.started,sim_time=world.time,revision=world.revision,prompt_version=world.prompt_versions,action_id=(v.get('action') or {}).get('id'),task_id=(v.get('action') or {}).get('zone'))
            health=dict(envelope,position=v['position'],battery=v['battery'],reserve=20,water=v.get('water'),lifecycle=v['lifecycle'],waiting_reason=waiting,fault=v.get('fault'),last_progress_revision=world.revision)
            if world.kind=='arm':
                health.update(joints=world.joints,tool_pose=world.tool_pose(),opening=world.opening,force=world.force,contact=world.holding,load=world.load,holding=world.holding,collision=world.collision)
            self.latest[key]=health
            self.motion.append(health)
            if heartbeat: world.event('heartbeat',key,telemetry=health)
        if heartbeat: self.last_heartbeat=now

    def flush(self,repo,world):
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
        artifacts=[repo.artifact(world.id,None,'movement',chunk,dict(units=UNITS,start=chunk[0]['sim_time'],end=chunk[-1]['sim_time'],samples=len(chunk))) for chunk in chunks]
        return artifacts

    @staticmethod
    def health_status(heartbeat_age,waiting,failures_without_progress):
        if heartbeat_age>5: return 'stale_heartbeat'
        if failures_without_progress>=3: return 'possible_loop'
        return 'healthy_wait' if waiting else 'healthy'
