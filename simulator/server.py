"""Loopback-only HTTP API and allowlisted local assets; no credentials leave Python."""
import argparse
import copy
import gzip
import json
import mimetypes
import pathlib
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .common import load_env,canonical,uid,digest,treatment_implementation_hash
from .engine import Mission,TERMINAL
from .runtime import Runtime
from .treatment import Treatment
from .care import PlantCare
from .manipulation import Manipulation
from .orchard_manipulation import OrchardManipulation
from .orchard_care import OrchardCare
from .fleet_care import FleetCareWorld,FleetCareRuntime,result_outcome
from .almanac import Season,DayClock
from . import timelapse
from .film import Film
from .treatment_runtime import TreatmentRuntime
from .persistence import Repository,StorageError
from .review import ReviewService
from .evaluation import Campaigns

ROOT=pathlib.Path(__file__).resolve().parent.parent
WORLDS={'irrigation':Treatment,'care':PlantCare,'arm':Manipulation}

def saved_outcomes(state):
    """Care outcomes recorded in a saved orchard checkpoint; unfinished workers count as untouched."""
    if state.get('mission_type')=='fleet_care':
        outcomes={}
        for i,a in state.get('assignments',{}).items():
            result=state.get('results',{}).get(a.get('session_id'))
            outcome=result and result_outcome(result)
            if outcome:outcomes[int(i)]=outcome
        return outcomes
    return {0:dict(weed_removed=bool(state['extracted']))} if state.get('arena')=='orchard' and 'extracted' in state else {}


class App:
    def __init__(self,recover_season=True):
        self.repository=Repository(); self.fleet=TreatmentRuntime(OrchardManipulation(),repository=self.repository,config=dict(mode='vision',engine='crusoe',speed=4,arena='orchard',treatment_code_hash=treatment_implementation_hash()))
        self.treatment=TreatmentRuntime(repository=self.repository)
        self.reset_lock=threading.RLock(); self.campaigns=Campaigns(self)
        # The orchard calendar outlives individual missions. Each day's world saves its own conditions.
        self.season=Season(7); self.clock=DayClock(self.season); self.season_lock=threading.Lock()
        self.plan=dict(mission='full_care',mode='demo',speed=8); self.carry={}; self.season_notice=None; self.blocked_days=0
        threading.Thread(target=self.season_loop,daemon=True).start()
        if recover_season: threading.Thread(target=self.recover_season,daemon=True).start()

    def day_plan(self,body):
        plan=dict(self.plan,**{k:body[k] for k in ('mission','mode','speed') if k in body})
        if plan['mission'] not in ('weeding','watering','full_care'): raise ValueError('unknown orchard mission')
        if plan['speed'] not in (1,4,8,16): raise ValueError('speed must be 1/4/8/16')
        if plan['mission']=='watering' and plan['mode'] not in ('demo','live'): raise ValueError('invalid fleet mode')
        return plan

    def day_outcomes(self,runtime):
        record=getattr(runtime.world,'season',None)
        if not record or record['seed']!=self.season.seed or record['day']!=self.season.day: return dict(self.carry)
        if isinstance(runtime,FleetCareRuntime): return runtime.day_outcomes()
        with runtime.lock: return saved_outcomes(runtime.world.__dict__)

    def begin_day(self,season,body):
        """Close the current day, then create and start the given day's mission. Agents are always on."""
        with self.reset_lock:
            plan=self.day_plan(body)
            snapshot=self.reset(False,dict(plan,seed=(season.seed+season.day-1)%100001),season)
            with self.season_lock:
                self.season=season;self.clock.reset(season);self.carry={};self.plan=plan;self.season_notice=None
            self.fleet.start()
            return snapshot

    def next_day(self,body,automatic=False):
        with self.reset_lock:
            world=self.fleet.world;status=world.status
            if getattr(world,'season',None):self.blocked_days=self.blocked_days+1 if status=='blocked' else 0
            if automatic and self.blocked_days>=2:
                with self.season_lock:self.clock.auto_advance=False;self.season_notice='Auto-advance stopped after two blocked days; inspect the mission journal, then start the next day.'
                return self.fleet.snapshot()
            return self.begin_day(self.season.next_day(self.day_outcomes(self.fleet) if self.season.day else {}),body)

    def new_season(self,body):
        seed=body.get('seed',7)
        if type(seed)!=int or not 0<=seed<=100000: raise ValueError('seed must be 0..100000')
        with self.reset_lock:
            self.blocked_days=0
            return self.begin_day(Season(seed).next_day(),body)

    def pace(self,body):
        with self.season_lock:
            if 'day_minutes' in body:
                if body['day_minutes'] not in (5,10,20,40,80): raise ValueError('day length must be 5/10/20/40/80 minutes')
                self.clock.day_minutes=body['day_minutes']
            if 'auto_advance' in body:
                if type(body['auto_advance'])!=bool: raise ValueError('auto_advance must be boolean')
                self.clock.auto_advance=body['auto_advance'];self.season_notice=None
                if body['auto_advance']:self.blocked_days=0
        return self.epoch_view()

    def season_loop(self):
        previous=time.monotonic()
        while True:
            time.sleep(.25);now=time.monotonic();runtime=self.fleet
            status='storage_blocked' if runtime.storage_error else runtime.world.status
            with self.season_lock:
                self.clock.tick(now-previous,status,now);due=self.clock.due(now)
            previous=now
            if due:
                try:self.next_day({},automatic=True)
                except Exception as exc:
                    with self.season_lock:self.clock.auto_advance=False;self.season_notice=f'Auto-advance stopped: {exc}'

    def recover_season(self):
        """Continue the latest saved season after a restart; Next day then begins the following day."""
        try:
            rows=self.repository.read('sessions','select=id,metadata&order=started_at.desc,id.desc&limit=25')
            # Worker sessions inherit the parent's configuration; only the parent holds the season.
            configs=[((r.get('metadata') or {}).get('configuration') or {},r) for r in rows]
            row=next((r for c,r in configs if c.get('season_day') and not c.get('parent_session_id')),None)
            if not row: return
            state=self.repository.restore(row['id']);season=Season.from_record(state['season'])
            with self.reset_lock:
                if self.season.day or getattr(self.fleet.world,'season',None): return
                with self.season_lock:
                    self.season=season;self.clock.reset(season);self.clock.clock=self.clock.night;self.clock.mode='night'
                    self.carry=saved_outcomes(state);self.season_notice=f'Recovered season {season.seed} at day {season.day}. Next day continues it.'
        except Exception:
            pass

    def epoch_view(self):
        with self.season_lock:
            view=self.clock.view();season=self.season;view.update(history=copy.deepcopy(season.history[-14:]),notice=self.season_notice,plan=dict(self.plan))
        view['trees']=season.view_trees(self.day_outcomes(self.fleet) if season.day else {})
        return view

    def start_film(self,body):
        """A deterministic scripted season for presentation; independent of the live fleet and storage."""
        seed=body.get('seed',7);days=body.get('days',14)
        if type(seed)!=int or not 0<=seed<=100000: raise ValueError('seed must be 0..100000')
        film=Film(seed,days);reel=body.get('reel')
        if reel is not None:timelapse.write_manifest(reel,dict(kind='season_film',controller='scripted',seed=seed,days=days,frames=film.total,fps=30))
        self.film=dict(film=film,frames=film.frames(),next=0,reel=reel)
        return dict(seed=seed,days=days,total=film.total,reel=reel)

    def film_frames(self,body):
        film=getattr(self,'film',None);start=body.get('start');count=body.get('count',10)
        if not film or body.get('reel')!=film['reel']: raise ValueError('start the film first')
        if type(start)!=int or type(count)!=int or not 1<=count<=60: raise ValueError('invalid frame range')
        if start<film['next']:film.update(frames=film['film'].frames(),next=0)  # deterministic replay to a resumed index
        frames=[]
        for state in film['frames']:
            film['next']+=1
            if film['next']>start:frames.append(state)
            if len(frames)==count:break
        return dict(start=start,frames=frames,total=film['film'].total)

    def reset(self,treatment,body,season=None):
        with self.reset_lock:
            seed=body.get('seed',8 if treatment else 7)
            if type(seed)!=int or not 0<=seed<=100000: raise ValueError('seed must be 0..100000')
            conditions=None
            if treatment:
                kind=body.get('kind','irrigation'); cls=WORLDS.get(kind)
                if not cls: raise ValueError('invalid mission kind')
                mode=body.get('mode','pixels')
                if mode not in ('pixels','vision'): raise ValueError('invalid treatment mode')
                if kind=='arm' and mode!='vision': raise ValueError('arm requires live image decisions')
                world=cls(seed,body.get('trial','wrist' if kind=='arm' else 'baseline'))
            else:
                mission=body.get('mission','weeding')
                if mission not in ('weeding','watering','full_care'):raise ValueError('unknown orchard mission')
                mode='vision' if mission in ('weeding','full_care') else body.get('mode','demo')
                if mission=='watering' and mode not in ('demo','live'): raise ValueError('invalid fleet mode')
                conditions=season.conditions() if season and season.day else None
                if mission=='full_care':world=FleetCareWorld(seed,body.get('tree_count',10),conditions=conditions)
                elif mission=='weeding':world=OrchardManipulation(conditions[0]['weed']['specimen_seed'],growth=conditions[0]['weed']) if conditions else OrchardManipulation(seed)
                else:world=Mission(seed)
                if conditions:world.season=season.record()
            engine=body.get('engine','crusoe')
            if engine not in ('crusoe','nemotron','gemma','gemini'): raise ValueError('invalid inference engine')
            speed=body.get('speed',4 if treatment else 8)
            if speed not in (1,4,8,16): raise ValueError('speed must be 1/4/8/16')
            old=self.treatment if treatment else self.fleet
            if old.persisted:
                if old.storage_error: raise ValueError('recover storage before replacing a session')
                old.pause('aborted' if old.world.status not in ('completed','failed','blocked','aborted') else old.world.status)
                if old.storage_error: raise ValueError('session replacement paused by storage failure')
            old.close()
            config=dict(mode=mode,engine=engine,speed=speed,**({'prompt_version':body['prompt_version']} if body.get('prompt_version') else {}))
            if body.get('campaign_id'): config['campaign_id']=body['campaign_id']
            if body.get('model_pins'): config.update(models=body['model_pins'],provider_base=body['provider_base'])
            from .common import implementation_hash,treatment_implementation_hash
            config['code_hash']=implementation_hash()
            if world.kind!='fleet' or getattr(world,'arena',None)=='orchard':config['treatment_code_hash']=treatment_implementation_hash()
            if getattr(world,'arena',None)=='orchard':config['arena']='orchard'
            if conditions:config.update(season_seed=season.seed,season_day=season.day)
            runtime=(FleetCareRuntime if getattr(world,'mission_type',None)=='fleet_care' else TreatmentRuntime if world.kind!='fleet' else Runtime)(world,self.repository,config)
            if treatment: self.treatment=runtime
            else: self.fleet=runtime
            with runtime.lock: runtime.persist()
            return runtime.snapshot()

class Handler(BaseHTTPRequestHandler):
    server_version='Wallne/1'
    def log_message(self,format,*args): pass

    def finish(self):
        try: super().finish()
        finally:
            for repo in (self.server.app.repository,self.server.app.fleet.repository,self.server.app.treatment.repository): repo.close_current()

    def check_origin(self):
        port=self.server.server_port
        allowed={f'127.0.0.1:{port}',f'localhost:{port}'}
        if self.headers.get('Host') not in allowed: raise ValueError('local Host required')
        origin=self.headers.get('Origin')
        if origin and origin not in {'http://'+h for h in allowed}: raise ValueError('local Origin required')
        if self.headers.get('Sec-Fetch-Site')=='cross-site': raise ValueError('cross-site request rejected')

    def send(self,data,status=200,content_type='application/json'):
        raw=data if isinstance(data,bytes) else canonical(data).encode()
        self.send_response(status); self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        try: self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError): pass

    def do_GET(self):
        try:
            self.check_origin(); parsed=urllib.parse.urlsplit(self.path); path=urllib.parse.unquote(parsed.path); query=urllib.parse.parse_qs(parsed.query)
            app=self.server.app
            if path=='/api/fixtures/arm':
                pose=query.get('pose',['initial'])[0]
                if pose not in ('initial','aligned','approach','recovery','offset'): raise ValueError('unknown fixture')
                world=Manipulation(7,'wrist')
                if pose!='initial':
                    from .arm import ik
                    x,_,z=world.weed['position'];offset,height,back={'aligned':(0,.15,0),'approach':(0,.35,.12),'recovery':(.12,.25,.12),'offset':(-.12,.15,0)}[pose];world.joints=ik([x+offset,height,z+back,0,0,0],world.base())
                result=world.snapshot();result['diagnostic_fixture']=pose
                return self.send(result)
            if path in ('/api/state','/api/export'):
                state=app.fleet.snapshot();state['epoch']=app.epoch_view()
                return self.send(state)
            if path=='/api/timelapse': return self.send(dict(reels=timelapse.reels()))
            if path in ('/api/treatment/state','/api/treatment/export'): return self.send(app.treatment.snapshot())
            if path.startswith('/api/treatment/frame/'):
                if query.get('mission',[''])[0]!=app.treatment.world.id: raise ValueError('cross-mission frame')
                raw=app.treatment.frame_bytes.get(path.rsplit('/',1)[1])
                if raw is None: raise ValueError('unknown frame; use saved session artifact')
                return self.send(raw,content_type='image/png')
            if path=='/api/sessions': return self.send(app.repository.sessions(query.get('before',[None])[0],query.get('before_id',[None])[0]))
            if path.startswith('/api/sessions/'):
                return self.session_get(path,query)
            if path in ('/api/reviews','/api/prompt-versions','/api/evaluations','/api/evaluation-campaigns'):
                import uuid
                cursor=query.get('before',[None])[0];ident=query.get('before_id',[None])[0]
                from .common import cursor_timestamp
                where=''
                if cursor:
                    cursor=urllib.parse.quote(cursor_timestamp(cursor),safe=':-.')
                    where=f'or=(created_at.lt.{cursor},and(created_at.eq.{cursor},id.lt.{str(uuid.UUID(ident))}))&' if ident else f'created_at=lt.{cursor}&'
                rows=app.repository.read(path.rsplit('/',1)[1].replace('-','_'),where+'order=created_at.desc,id.desc&limit=50')
                if path=='/api/evaluation-campaigns' and app.campaigns.active:
                    rows=[dict(r,status=app.campaigns.active['status']) if r['id']==app.campaigns.active['id'] else r for r in rows]
                return self.send(rows)
            for collection in ('reviews','prompt-versions','evaluations','evaluation-campaigns'):
                if path.startswith('/api/'+collection+'/'):
                    import uuid
                    ident=str(uuid.UUID(path.rsplit('/',1)[1]))
                    rows=app.repository.read(collection.replace('-','_'),f'id=eq.{ident}&limit=1')
                    return self.send(rows[0] if rows else {'error':'record not found'},200 if rows else 404)
            if path.startswith('/api/'): return self.send({'error':'unknown route'},404)
            if '\x00' in path or '\\' in path or '..' in path.split('/'): raise ValueError('invalid static path')
            if path.startswith('/vendor/ez-tree/'):
                base=ROOT/'node_modules/@dgreenheck/ez-tree/build'; relative=path[len('/vendor/ez-tree/'):]
            elif path.startswith('/vendor/'):
                base=ROOT/'node_modules/three/build'; relative=path[len('/vendor/'):]
            else: base=ROOT/'web'; relative=path.lstrip('/') or 'index.html'
            file=(base/relative).resolve()
            if base.resolve() not in file.parents or not file.is_file(): return self.send({'error':'not found'},404)
            if file.suffix not in ('.js','.mjs','.html','.css','.png','.svg','.ico','.json'): return self.send({'error':'not found'},404)
            return self.send(file.read_bytes(),content_type=mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
        except ValueError as exc: self.send({'error':str(exc)},400)
        except StorageError as exc: self.send({'error':str(exc)},503)
        except Exception: self.send({'error':'internal request failure'},500)

    def session_get(self,path,query):
        import uuid
        parts=path.strip('/').split('/'); sid=str(uuid.UUID(parts[2])); repo=self.server.app.repository
        if len(parts)==3: return self.send(repo.read('sessions',f'id=eq.{sid}&limit=1'))
        resource=parts[3]
        if resource=='artifacts' and len(parts)==5:
            aid=str(uuid.UUID(parts[4])); raw,a=repo.artifact_bytes(sid,aid)
            return self.send(raw,content_type='image/png' if a['kind']=='frame' else 'application/gzip')
        if resource=='events':
            after=int(query.get('after',['0'])[0]); robot=query.get('robot',[''])[0]
            filters=f'session_id=eq.{sid}&sequence=gt.{max(0,after)}&order=sequence&limit=100'
            if robot in ('W1','W2','W3','W4','W5','R1','T1'): filters+=f'&robot_id=eq.{robot}'
            return self.send(repo.read('events',filters))
        if resource=='robots':
            if len(parts)!=6 or parts[5]!='telemetry' or parts[4] not in ('W1','W2','W3','W4','W5','R1','T1'): raise ValueError('unknown robot telemetry route')
            after=max(0,int(query.get('after',['0'])[0]))
            return self.send(repo.read('events',f'session_id=eq.{sid}&robot_id=eq.{parts[4]}&type=eq.heartbeat&sequence=gt.{after}&order=sequence&limit=100'))
        if resource in ('motions','artifacts'):
            after=max(0,int(query.get('after',['0'])[0]))
            after_id=query.get('after_id',[''])[0]
            cursor=f'or=(sequence.gt.{after},and(sequence.eq.{after},id.gt.{str(uuid.UUID(after_id))}))' if after_id else f'sequence=gt.{after}'
            return self.send(repo.read('artifacts',f'session_id=eq.{sid}&{cursor}'+('&kind=eq.movement' if resource=='motions' else '')+'&order=sequence,id&limit=100'))
        if resource=='export':
            record,valid=repo.checkpoint_record(sid)
            artifacts=repo.read('artifacts',f'session_id=eq.{sid}&order=sequence,id&limit=1000')
            return self.send(dict(session=repo.read('sessions',f'id=eq.{sid}&limit=1'),checkpoint=record['state'],checkpoint_integrity=dict(valid=valid,expected_hash=record['integrity_hash']),artifacts=artifacts,artifacts_next_cursor=dict(after=artifacts[-1]['sequence'],after_id=artifacts[-1]['id']) if len(artifacts)==1000 else None))
        raise ValueError('unknown session resource')

    def do_POST(self):
        try:
            self.check_origin()
            length=int(self.headers.get('Content-Length','0'))
            if not 0<=length<=3*1024*1024: raise ValueError('request too large')
            if self.headers.get_content_type()!='application/json': raise ValueError('application/json required')
            body=json.loads(self.rfile.read(length) or b'{}',parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
            if not isinstance(body,dict): raise ValueError('JSON object required')
            path=urllib.parse.urlsplit(self.path).path; app=self.server.app
            treatment=path.startswith('/api/treatment/'); runtime=app.treatment if treatment else app.fleet
            action=path.rsplit('/',1)[1]
            if path.startswith('/api/prompt-versions/') and action in ('activate','rollback'):
                import uuid
                version=str(uuid.UUID(path.split('/')[-2])); evaluation=str(uuid.UUID(body['evaluation_id']))
                if action=='activate':
                    from .common import treatment_implementation_hash
                    saved=app.repository.read('evaluations',f'id=eq.{evaluation}&limit=1')
                    if not saved or saved[0]['manifest'].get('treatment_code_hash')!=treatment_implementation_hash(): raise ValueError('evaluation implementation no longer matches current treatment code')
                return self.send(app.repository.rpc('wallne_activate',dict(p_version=version,p_evaluation=evaluation,p_rollback=action=='rollback')))
            if path=='/api/evaluations': return self.send(app.campaigns.start(**body))
            if path=='/api/evaluations/retry': return self.send(app.campaigns.retry(body['campaign_id']))
            if path.startswith('/api/sessions/') and action=='review':
                import uuid
                sid=str(uuid.UUID(path.split('/')[-2]))
                return self.send(ReviewService(app.repository).review_session(sid,**body))
            if path=='/api/prompt-candidates': return self.send(ReviewService(app.repository).create_candidate(**body))
            if path=='/api/next-day': return self.send(app.next_day(body))
            if path=='/api/season': return self.send(app.new_season(body))
            if path=='/api/epoch': return self.send(app.pace(body))
            if path=='/api/film/start': return self.send(app.start_film(body))
            if path=='/api/film/frames': return self.send(app.film_frames(body))
            if path=='/api/timelapse/frame': return self.send(timelapse.save_frame(body.get('reel'),body.get('index'),body.get('data_url'),body.get('meta')))
            if path=='/api/timelapse/render': return self.send(timelapse.render(body.get('reel'),body.get('fps',30)))
            allowed={'continue-care','reset','start','pause','breakdown','false-claim','retry','abort','stop','clog','fault','frame','depth','resume','command'}
            if action not in allowed or path not in ('/api/'+action,'/api/treatment/'+action): return self.send({'error':'unknown route'},404)
            if action=='reset':
                if 'model_pins' in body or 'provider_base' in body or 'prompt_version' in body: raise ValueError('prompt/model overrides are only available to frozen evaluation campaigns')
                return self.send(app.reset(treatment,body))
            if action=='continue-care':
                if treatment:raise ValueError('fleet continuation belongs to the main orchard')
                with app.reset_lock:
                    runtime=app.fleet
                    with runtime.lock:
                        for source_runtime in [runtime,*getattr(runtime,'children',{}).values()]:
                            with source_runtime.lock:
                                if source_runtime.storage_error or source_runtime.pending:raise ValueError('recover storage before continuing')
                                if source_runtime.world.status=='running' or source_runtime.futures or source_runtime.requests:raise ValueError('stop and finish inference accounting before continuing')
                        from .fleet_continuation import continue_fleet
                        replacement=continue_fleet(app.repository,body['session_id'],str(body.get('reason','Controller update'))[:400])
                        runtime.close();app.fleet=replacement
                        return self.send(replacement.snapshot())
            if action=='start' and treatment and runtime.world.kind=='arm':raise ValueError('Live arm runs now use the main orchard at /')
            if action=='start':
                with app.reset_lock:
                    runtime=app.treatment if treatment else app.fleet
                    runtime.start()
            elif action in ('pause','abort','stop'): runtime.pause('paused' if action=='pause' else 'aborted')
            elif action=='retry': runtime.retry()
            elif action=='resume': runtime.restore(body['session_id'])
            elif action=='frame' and isinstance(runtime,(TreatmentRuntime,FleetCareRuntime)): return self.send(runtime.accept_frame(body))
            elif action=='depth' and isinstance(runtime,(TreatmentRuntime,FleetCareRuntime)): return self.send(runtime.accept_depth(body))
            elif action=='command': return self.send(runtime.command(body.get('robot',runtime.world.robot['id'] if runtime.world.kind!='fleet' else 'orchestrator'),body['action'],body.get('arguments',{}),body.get('command_id')))
            elif action in ('clog','fault') and treatment:
                with runtime.lock:
                    if runtime.storage_error: raise ValueError('storage_blocked')
                    if runtime.world.status in TERMINAL: raise ValueError('terminal sessions are read-only')
                    tool=body.get('tool','nozzle')
                    if tool not in ('nozzle','gripper','fertilizer','vacuum'): raise ValueError('invalid tool')
                    runtime.world.faults[tool]=True; runtime.world.event('fault_injected',tool=tool); runtime.persist()
            elif action=='breakdown' and runtime.world.kind=='fleet':
                with runtime.lock:
                    if runtime.storage_error: raise ValueError('storage_blocked')
                    if runtime.world.status in TERMINAL: raise ValueError('terminal sessions are read-only')
                    robots=body.get('robots',['W1','W2'])
                    if not isinstance(robots,list) or not robots or len(robots)>5 or any(robot not in ('W1','W2','W3','W4','W5') for robot in robots): raise ValueError('invalid workers')
                    for robot in dict.fromkeys(robots): runtime.world.breakdown(robot)
                    runtime.persist()
            elif action=='false-claim' and runtime.world.kind=='fleet': return self.send(runtime.command('orchestrator','claim_complete'))
            else: raise ValueError('action unavailable in this mode')
            return self.send(runtime.snapshot())
        except (ValueError,KeyError,TypeError) as exc: self.send({'error':str(exc) if isinstance(exc,ValueError) else 'invalid request arguments'},400)
        except StorageError as exc: self.send({'error':str(exc)},503)
        except Exception: self.send({'error':'internal request failure'},500)


def main():
    load_env(ROOT/'.env')
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765); args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler); server.daemon_threads=True; server.app=App()
    print(f'Wall-ne: http://127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.app.fleet.close(); server.app.treatment.close(); server.server_close()

if __name__=='__main__': main()
