"""Deterministic season film: a scripted fleet performs full care day after day.

The script reads simulator truth (weed, basin and pest positions) and issues the
ordinary care commands, so arm kinematics, collision checks, metering and every
per-tree check still decide each outcome. Simulated time advances in fixed
steps, so a seed always yields the same frames. Nothing here is persisted as
mission evidence and no model is called.
"""
import copy
import math
from .almanac import Season,DayClock,DAY
from .orchard_care import OrchardCare
from .engine import Mission
from .camera import project_pixel,project_ground
from .common import uid

WORKERS=('W1','W2','W3','W4','W5')
STEP=.05           # physics step, simulated seconds
DWELL=1.5          # pause between commands so each pose is visible
WORK_END=15.5*3600 # orchard clock when the day's work has been shown
WORK_FRAMES=240    # frames spanning dawn to WORK_END
EVENING_FRAMES=96  # frames sweeping WORK_END to nightfall
NIGHT_FRAMES=24    # frames holding the night sky


class FilmError(RuntimeError):
    pass


def inside(u,v,margin=.12):
    return min(1-margin,max(margin,u)),min(1-margin,max(margin,v))


class ScriptedWorker:
    """Drives one single-tree OrchardCare world through every stage from simulator truth."""
    def __init__(self,world):
        self.world=world;self.wait=0.

    def frame(self):
        w=self.world
        if w.frame is None or w.frame['revision']!=w.revision or w.frame['phase']!=w.phase:
            w.frame_request=None;w.request_frame();w.accept_frame(w.frame_request['id'],dict(id=uid(),ready=True))
        return w.frame['id']

    def pixel(self,point):
        return inside(*project_pixel(self.world.camera(),point))

    def do(self,action,**args):
        w=self.world;receipt=w.command(uid(),w.robot['id'],action,**args)
        if not receipt['accepted']:raise FilmError(f'{w.robot["id"]} {action} rejected in {w.phase}: {receipt.get("reason")}')
        if not w.robot['action']:w.record_control_progress(action)
        self.wait=DWELL

    def move(self,x,y,z):
        self.do('move_arm',pose=[x,y,z,0,0,0])

    def act(self):
        w=self.world;phase=w.phase;tx,_,tz=w.orchard['tree']['position']
        if phase=='inspection':self.do('inspect_tree',frame_id=self.frame())
        elif phase in ('irrigation','fertilizer'):
            water=phase=='irrigation'
            if water and (w.moisture_reading is None or w.moisture_reading['dose_sequence']!=w.dose_sequence):self.do('read_moisture')
            elif not water and w.fertilizer_meter is None:self.do('read_application')
            elif (w.moisture_reading['value']>=65-1e-6) if water else (w.fertilizer_meter['effective']>=w.fertilizer_meter['prescription']-1e-6):self.do('next_stage',frame_id=self.frame())
            elif w.aim is None:
                u,v=self.pixel([tx,.08,tz+.35]);self.do('aim_nozzle',frame_id=self.frame(),u=u,v=v)
            else:self.do('water_tree' if water else 'fertilize_tree',frame_id=self.frame())
        elif phase=='pests':
            pest=next((p for p in w.pests if not p['removed']),None)
            if pest:
                u,v=self.pixel(pest['position']);self.do('remove_pest',frame_id=self.frame(),u=u,v=v)
            else:self.do('next_stage',frame_id=self.frame())
        elif phase=='extraction':self.extract()
        elif phase=='final':self.do('verify',frame_id=self.frame())

    def extract(self):
        w=self.world;weed=w.weed['position'];p=w.tool_pose()['position']
        if not w.nonempty_scan:
            fid=self.frame();u,v=self.pixel(weed);self.do('scan_lidar',frame_id=fid,u=u,v=v,span=.24)
            request=w.depth_request;points=[]
            for ru,rv in request['rays']:
                try:point=project_ground(request['camera'],ru,rv)
                except ValueError:point=None
                points.append([ru,rv,*point] if point and math.dist(point,request['camera']['position'])<5.9 else None)
            w.accept_depth(request['id'],request['frame_id'],request['revision'],points,dict(id=uid(),ready=True))
        elif w.deposited:self.do('verify',frame_id=self.frame())
        elif w.holding:
            if w.contact_ack is None:self.do('confirm_contact',frame_id=self.frame(),evidence='Measured grip load on the weed stem.')
            elif not w.extracted:self.move(weed[0],.45,weed[2])
            elif math.hypot(p[0]-w.bin[0],p[2]-w.bin[2])<.2 and .48<p[1]<1.3:self.do('open_gripper')
            else:self.move(w.bin[0],.75,w.bin[2])
        elif w.must_reopen or w.opening<.06:self.do('open_gripper')
        elif math.hypot(p[0]-weed[0],p[2]-weed[2])>.005:self.move(weed[0],.4,weed[2])
        elif w.crown_projection is None:
            u,v=self.pixel(weed);self.do('project_ground',frame_id=self.frame(),u=u,v=v)
        elif p[1]>.22:self.move(weed[0],.13,weed[2])
        elif not (w.alignment and w.alignment['aligned'] and w.alignment['revision']==w.revision):
            self.do('assess_alignment',frame_id=self.frame(),stem_between_fingers=True,depth_consistent=True,evidence='Stem centered between the open fingers.')
        else:self.do('set_gripper',opening=.01,force=30)


class FilmDay:
    """Five workers care for the season's ten trees; one rover uses the apron lane at a time."""
    def __init__(self,season):
        self.season=season;self.id=f'film-{season.seed}-{season.day}'
        self.tasks=OrchardCare(season.seed,10,conditions=season.conditions()).tasks
        self.queue=list(range(len(self.tasks)));self.children={};self.done={};self.lane=None;self.time=0.
        self.parked={w:None for w in WORKERS};self.vehicles=Mission(season.seed).vehicles;self.vehicles['W5']['lifecycle']='idle'

    def assign(self):
        for worker in WORKERS:
            child=self.children.get(worker)
            if child and child.world.status=='completed':
                self.done[child.index]=child.world;self.parked[worker]=copy.deepcopy(child.world.robot);del self.children[worker];child=None
            if not child and self.queue:
                index=self.queue.pop(0);world=OrchardCare(self.season.seed+index,1,worker,self.tasks[index])
                if self.parked[worker]:world.robot.update(battery=self.parked[worker]['battery'],minimum_battery=self.parked[worker]['minimum_battery'])
                world.status='running';script=ScriptedWorker(world);script.index=index;self.children[worker]=script

    @property
    def settled(self):
        return not self.queue and not self.children

    def step(self):
        self.assign();self.time+=STEP
        if self.lane and (self.lane not in self.children or (self.children[self.lane].world.robot['action'] or {}).get('kind')!='navigate'):self.lane=None
        for worker,script in self.children.items():
            w=script.world
            if w.status!='running':raise FilmError(f'{worker} stopped: {w.status} · {w.feedback}')
            navigating=(w.robot['action'] or {}).get('kind')=='navigate'
            if navigating and self.lane not in (None,worker):continue
            if navigating:self.lane=worker
            if w.robot['action']:
                w.tick(STEP)
                if not w.robot['action'] and w.kind=='arm':w.record_control_progress('motion_completed')
            elif script.wait>0:script.wait-=STEP
            else:
                before=w.phase;w.tick(STEP)  # automatic travel, return and dock service
                if not w.robot['action'] and w.phase==before:script.act()

    def outcomes(self):
        out={i:w.tree_outcome() for i,w in self.done.items()}
        for script in self.children.values():out[script.index]=script.world.tree_outcome()
        return out

    def state(self):
        """Renderer state in the fleet-care snapshot shape the orchard scene already reads."""
        vehicles=copy.deepcopy(self.vehicles)
        for worker,robot in self.parked.items():
            if robot:vehicles[worker]=copy.deepcopy(robot)
        workers={}
        for worker,script in self.children.items():
            w=script.world;vehicles[worker]=copy.deepcopy(w.robot)
            workers[worker]=dict(id=w.id,status=w.status,phase=w.phase,observations=dict(tool_pose=w.tool_pose()),opening=w.opening,bin=w.bin,weed=copy.deepcopy(w.weed),
                                 extracted=w.extracted,holding=w.holding,deposited=w.deposited,unloaded_total=w.unloaded_total,collected_total=w.collected_total,
                                 stage_verified=w.stage_verified,camera=w.camera(),task_index=script.index)
        inventory=dict(id=self.id,seed=self.season.seed,trial='precision',weeds=[],protected=[],pests=[],beneficial=[])
        live={script.index:script.world for script in self.children.values()}
        for i,task in enumerate(self.tasks):
            if i in live:inventory['weeds'].append(copy.deepcopy(live[i].weed));inventory['pests']+=copy.deepcopy(live[i].pests)
            else:
                done=i in self.done;inventory['weeds'].append(dict(task['weed'],removed=done));inventory['pests']+=[dict(p,removed=done) for p in task['pests']]
            inventory['protected']+=task['protected'];inventory['beneficial']+=task['beneficial']
        return dict(id=self.id,arena='orchard',mission_type='fleet_care',status='completed' if self.settled else 'running',vehicles=vehicles,care_workers=workers,
                    care_inventory=inventory,tasks=[dict(index=i) for i in range(len(self.tasks))],cared=len(self.done))


class Film:
    """Frames for a season: work from dawn to mid-afternoon, then an evening sweep and night."""
    def __init__(self,seed=7,days=14):
        if type(days)!=int or not 1<=days<=60:raise ValueError('days must be 1..60')
        self.seed=seed;self.days=days

    def work_seconds(self,season):
        day=FilmDay(season)
        while not day.settled:
            day.step()
            if day.time>3*3600:raise FilmError(f'day {season.day} did not settle')
        return day.time,day.outcomes()

    @property
    def total(self):
        return self.days*(WORK_FRAMES+EVENING_FRAMES+NIGHT_FRAMES)

    def frames(self):
        season=Season(self.seed).next_day();self.series=[]
        for _ in range(self.days):
            trees=season.trees
            self.series.append(dict(day=season.day,moisture=round(sum(t['moisture'] for t in trees)/len(trees),1),pests=sum(t['pests'] for t in trees),
                                    weed_size=round(sum(t['weed']['size'] for t in trees)/len(trees),3),cared=0))
            # A dry run fixes the day's length so every day's work fills the same frames.
            seconds,_=self.work_seconds(season)
            day=FilmDay(season);clock=DayClock(season);dawn=clock.clock;per=seconds/WORK_FRAMES
            for frame in range(WORK_FRAMES):
                target=per*(frame+1)
                while day.time<target-1e-9 and not day.settled:day.step()
                yield self.frame(day,season,dawn+(WORK_END-dawn)*frame/(WORK_FRAMES-1),'working')
            outcomes=day.outcomes();self.series[-1]['cared']=sum(bool(o.get('cared')) for o in outcomes.values())
            for frame in range(EVENING_FRAMES):
                yield self.frame(day,season,WORK_END+(clock.night-WORK_END)*(frame+1)/EVENING_FRAMES,'settling',outcomes)
            for frame in range(NIGHT_FRAMES):
                yield self.frame(day,season,clock.night,'night',outcomes)
            season=season.next_day(outcomes)

    def frame(self,day,season,clock,mode,outcomes=None):
        state=day.state();live=outcomes if outcomes is not None else day.outcomes()
        if outcomes is None:self.series[-1]['cared']=len(day.done)
        epoch=dict(season.environment(clock),day=season.day,seed=season.seed,mode=mode,history=copy.deepcopy(season.history),trees=season.view_trees(live),series=copy.deepcopy(self.series),days=self.days)
        state.update(epoch=epoch,controller='scripted');return state
