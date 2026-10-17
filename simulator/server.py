"""Loopback-only HTTP API and allowlisted local assets; no credentials leave Python."""
import argparse
import gzip
import json
import mimetypes
import pathlib
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .common import load_env,canonical,uid,digest
from .engine import Mission,TERMINAL
from .runtime import Runtime
from .treatment import Treatment
from .care import PlantCare
from .manipulation import Manipulation
from .treatment_runtime import TreatmentRuntime
from .persistence import Repository,StorageError
from .review import ReviewService
from .evaluation import Campaigns

ROOT=pathlib.Path(__file__).resolve().parent.parent
WORLDS={'irrigation':Treatment,'care':PlantCare,'arm':Manipulation}

class App:
    def __init__(self):
        self.repository=Repository(); self.fleet=Runtime(repository=self.repository)
        self.treatment=TreatmentRuntime(repository=self.repository)
        self.reset_lock=threading.Lock(); self.campaigns=Campaigns(self)

    def reset(self,treatment,body):
        with self.reset_lock:
            seed=body.get('seed',8 if treatment else 7)
            if type(seed)!=int or not 0<=seed<=100000: raise ValueError('seed must be 0..100000')
            if treatment:
                kind=body.get('kind','irrigation'); cls=WORLDS.get(kind)
                if not cls: raise ValueError('invalid mission kind')
                mode=body.get('mode','pixels')
                if mode not in ('pixels','vision'): raise ValueError('invalid treatment mode')
                if kind=='arm' and mode!='vision': raise ValueError('arm requires live image decisions')
                world=cls(seed,body.get('trial','wrist' if kind=='arm' else 'baseline'))
            else:
                mode=body.get('mode','demo')
                if mode not in ('demo','live'): raise ValueError('invalid fleet mode')
                world=Mission(seed)
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
            if treatment:config['treatment_code_hash']=treatment_implementation_hash()
            runtime=(TreatmentRuntime if treatment else Runtime)(world,self.repository,config)
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
            if path in ('/api/state','/api/export'): return self.send(app.fleet.snapshot())
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
            if file.suffix not in ('.js','.mjs','.html','.css','.png','.svg','.json'): return self.send({'error':'not found'},404)
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
            allowed={'reset','start','pause','breakdown','false-claim','retry','abort','stop','clog','fault','frame','depth','resume','command'}
            if action not in allowed or path not in ('/api/'+action,'/api/treatment/'+action): return self.send({'error':'unknown route'},404)
            if action=='reset':
                if 'model_pins' in body or 'provider_base' in body or 'prompt_version' in body: raise ValueError('prompt/model overrides are only available to frozen evaluation campaigns')
                return self.send(app.reset(treatment,body))
            if action=='start': runtime.start()
            elif action in ('pause','abort','stop'): runtime.pause('paused' if action=='pause' else 'aborted')
            elif action=='retry': runtime.retry()
            elif action=='resume': runtime.restore(body['session_id'])
            elif action=='frame' and treatment: return self.send(runtime.accept_frame(body))
            elif action=='depth' and treatment: return self.send(runtime.accept_depth(body))
            elif action=='command': return self.send(runtime.command(body.get('robot','T1' if treatment else 'orchestrator'),body['action'],body.get('arguments',{}),body.get('command_id')))
            elif action in ('clog','fault') and treatment:
                with runtime.lock:
                    if runtime.storage_error: raise ValueError('storage_blocked')
                    if runtime.world.status in TERMINAL: raise ValueError('terminal sessions are read-only')
                    tool=body.get('tool','nozzle')
                    if tool not in ('nozzle','gripper','fertilizer','vacuum'): raise ValueError('invalid tool')
                    runtime.world.faults[tool]=True; runtime.world.event('fault_injected',tool=tool); runtime.persist()
            elif action=='breakdown' and not treatment:
                with runtime.lock:
                    if runtime.storage_error: raise ValueError('storage_blocked')
                    if runtime.world.status in TERMINAL: raise ValueError('terminal sessions are read-only')
                    robots=body.get('robots',['W1','W2'])
                    if not isinstance(robots,list) or not robots or len(robots)>5 or any(robot not in ('W1','W2','W3','W4','W5') for robot in robots): raise ValueError('invalid workers')
                    for robot in dict.fromkeys(robots): runtime.world.breakdown(robot)
                    runtime.persist()
            elif action=='false-claim' and not treatment: return self.send(runtime.command('orchestrator','claim_complete'))
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
