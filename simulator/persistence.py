"""Supabase Data/Storage API. Errors are sanitized before crossing the API boundary."""
import gzip
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from .common import canonical, digest, uid

class StorageError(RuntimeError):
    pass

class Repository:
    def __init__(self, url=None, key=None):
        self.url=(url or os.getenv('SUPABASE_URL','')).rstrip('/')
        self.key=key or os.getenv('SUPABASE_SECRET_KEY','')
        self.bucket=os.getenv('SUPABASE_STORAGE_BUCKET','robot-session-artifacts')
        self.writer=uid()
        self.leases={}

    def request(self, method, path, data=None, content_type='application/json'):
        if not self.url or not self.key: raise StorageError('Supabase backend credentials are missing')
        body=data if isinstance(data,bytes) else canonical(data).encode() if data is not None else None
        headers={'apikey':self.key,'Authorization':'Bearer '+self.key,'Content-Type':content_type,'Prefer':'return=representation'}
        req=urllib.request.Request(self.url+path,data=body,method=method,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=10) as response:
                raw=response.read(16*1024*1024)
                return json.loads(raw) if 'json' in response.headers.get('Content-Type','') else raw
        except urllib.error.HTTPError as exc:
            raise StorageError(f'Supabase {method} failed (HTTP {exc.code})') from None
        except (OSError,ValueError):
            raise StorageError('Supabase connection unavailable') from None

    def rpc(self,name,args):
        return self.request('POST','/rest/v1/rpc/'+name,args)

    def create(self,world,config):
        meta=dict(id=world.id,kind=world.kind,seed=world.seed,contract=getattr(world,'contract',{}),contract_hash=getattr(world,'contract_hash',''),version=world.version,configuration=config,prompt_versions=world.prompt_versions)
        self.rpc('wallne_create',{'p_session':meta})
        return self.lease(world.id)

    def lease(self,session):
        result=self.rpc('wallne_lease',{'p_session':session,'p_writer':self.writer})
        self.leases[session]=result
        return result

    def artifact(self, session, robot, kind, data, metadata):
        raw=data if isinstance(data,bytes) else gzip.compress(canonical(data).encode(),mtime=0)
        sha=hashlib.sha256(raw).hexdigest()
        ext='png' if kind=='frame' else 'json.gz'
        key=f'{session}/{kind}/{sha}.{ext}'
        # Content-addressed retries: verify existing bytes on duplicate/upload uncertainty.
        path='/storage/v1/object/'+urllib.parse.quote(self.bucket)+'/'+key
        try:
            self.request('POST',path,raw,'image/png' if kind=='frame' else 'application/gzip')
        except StorageError:
            existing=self.request('GET',path)
            if not isinstance(existing,bytes) or hashlib.sha256(existing).hexdigest()!=sha: raise StorageError('artifact upload not durable')
        return dict(id=uid(),session_id=session,robot_id=robot,kind=kind,object_key=key,sha256=sha,metadata=metadata,ready=True)

    def batch(self,world,expected,robots,artifacts):
        state=world.checkpoint()
        # Full event history lives in events; checkpoints retain bounded policy history.
        state['events']=state['events'][-100:]
        return dict(session_id=world.id,batch_id=uid(),writer=self.writer,fence=self.leases[world.id]['fence'],expected_sequence=expected,
                    sequence=world.seq,revision=world.revision,status=world.status,events=[e for e in world.events if e['sequence']>expected],
                    actions=list(world.receipts.values()),robots=robots,artifacts=artifacts,state=state,integrity_hash=digest(state),verification=world.verify())

    def commit(self,batch):
        return self.rpc('wallne_commit',{'p_batch':batch})

    def read(self,table,query=''):
        if table not in ('sessions','events','actions','checkpoints','artifacts','robot_sessions','reviews','prompt_versions','evaluations','prompt_activations'): raise ValueError('invalid table')
        return self.request('GET','/rest/v1/'+table+'?'+query)

    def sessions(self):
        return self.read('sessions','select=*&order=started_at.desc&limit=50')

    def restore(self,session):
        rows=self.read('checkpoints',f'session_id=eq.{session}&order=sequence.desc&limit=1')
        if not rows: raise StorageError('No committed checkpoint exists')
        row=rows[0]
        if digest(row['state'])!=row['integrity_hash']: raise StorageError('Checkpoint integrity mismatch')
        return row['state']

    def artifact_bytes(self,session,artifact_id):
        rows=self.read('artifacts',f'session_id=eq.{session}&id=eq.{artifact_id}&limit=1')
        if not rows: raise ValueError('unknown artifact')
        a=rows[0]
        raw=self.request('GET','/storage/v1/object/'+urllib.parse.quote(self.bucket)+'/'+a['object_key'])
        if hashlib.sha256(raw).hexdigest()!=a['sha256']: raise StorageError('Artifact integrity mismatch')
        return raw,a
