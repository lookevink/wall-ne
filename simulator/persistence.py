"""Supabase Data/Storage API. Errors are sanitized before crossing the API boundary."""
import copy
import http.client
import threading
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
        self.connections=threading.local()

    def request(self, method, path, data=None, content_type='application/json'):
        if not self.url or not self.key: raise StorageError('Supabase backend credentials are missing')
        body=data if isinstance(data,bytes) else canonical(data).encode() if data is not None else None
        headers={'apikey':self.key,'Authorization':'Bearer '+self.key,'Content-Type':content_type,'Prefer':'return=representation'}
        url=urllib.parse.urlsplit(self.url)
        connection=getattr(self.connections,'connection',None)
        if connection is None:
            cls=http.client.HTTPSConnection if url.scheme=='https' else http.client.HTTPConnection
            connection=cls(url.hostname,url.port,timeout=10)
            self.connections.connection=connection
        try:
            connection.request(method,(url.path.rstrip('/')+path),body=body,headers=headers)
            response=connection.getresponse(); raw=response.read(16*1024*1024)
            if response.status>=400:
                label=f'Supabase {method} failed (HTTP {response.status})'
                try:
                    message=json.loads(raw).get('message','')
                    for known in ('writer lease held','writer fenced','sequence conflict','event sequence gap','checkpoint sequence mismatch','evidence is append-only'):
                        if message==known: label='Supabase: '+known
                except (ValueError,AttributeError): pass
                raise StorageError(label)
            return json.loads(raw) if 'json' in response.getheader('Content-Type','') else raw
        except StorageError:
            raise
        except (OSError,ValueError,http.client.HTTPException):
            connection.close(); self.connections.connection=None
            raise StorageError('Supabase connection unavailable') from None

    def close_current(self):
        connection=getattr(self.connections,'connection',None)
        if connection: connection.close();self.connections.connection=None

    def rpc(self,name,args):
        return self.request('POST','/rest/v1/rpc/'+name,args)

    def create(self,world,config):
        if not hasattr(world,'prompt_texts'):
            import uuid
            from .inference import PROMPT
            texts={}; versions_by_role={}
            for role in world.prompt_versions:
                override=config.get('prompt_version')
                query=f'id=eq.{override}&limit=1' if override else f'role=eq.{role}&status=eq.active&limit=1'
                versions=self.read('prompt_versions',query)
                if versions:
                    version=versions[0]
                    if version['role']!=role: raise StorageError('Prompt role mismatch')
                else:
                    if override: raise StorageError('Unknown prompt version')
                    version=dict(id=str(uuid.uuid5(uuid.NAMESPACE_URL,role+PROMPT)),role=role,text=PROMPT,hash=digest(PROMPT),status='active')
                    existing=self.read('prompt_versions',f'id=eq.{version["id"]}&limit=1')
                    if not existing: self.request('POST','/rest/v1/prompt_versions',version)
                versions_by_role[role]=version['id'];texts[role]=version['text']
            world.prompt_versions=versions_by_role;world.prompt_texts=texts
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
                    sequence=world.seq,revision=world.revision,status=world.status,events=copy.deepcopy([e for e in world.events if e['sequence']>expected]),
                    actions=list(world.receipts.values()),robots=copy.deepcopy(robots),artifacts=copy.deepcopy(artifacts),state=state,integrity_hash=digest(state),verification=world.verify())

    def commit(self,batch):
        return self.rpc('wallne_commit',{'p_batch':batch})

    def read(self,table,query=''):
        if table not in ('sessions','events','actions','checkpoints','artifacts','robot_sessions','reviews','prompt_versions','evaluations','prompt_activations','evaluation_campaigns'): raise ValueError('invalid table')
        return self.request('GET','/rest/v1/'+table+'?'+query)

    def sessions(self,before=None,before_id=None):
        query='select=*&order=started_at.desc,id.desc&limit=50'
        if before:
            from .common import cursor_timestamp
            import uuid
            stamp=cursor_timestamp(before)
            ident=str(uuid.UUID(before_id))
            query+='&or=(started_at.lt.'+urllib.parse.quote(stamp,safe=':-.')+',and(started_at.eq.'+urllib.parse.quote(stamp,safe=':-.')+',id.lt.'+ident+'))'
        return self.read('sessions',query)

    def checkpoint_record(self,session):
        rows=self.read('checkpoints',f'session_id=eq.{session}&order=sequence.desc&limit=1')
        if not rows: raise StorageError('No committed checkpoint exists')
        row=rows[0]
        legacy=hashlib.sha256(json.dumps(row['state'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        valid=row['integrity_hash'] in (digest(row['state']),legacy)
        return row,valid

    def restore(self,session):
        row,valid=self.checkpoint_record(session)
        if not valid: raise StorageError('Checkpoint integrity mismatch; evidence remains available, resumption is blocked')
        return row['state']

    def artifact_bytes(self,session,artifact_id):
        rows=self.read('artifacts',f'session_id=eq.{session}&id=eq.{artifact_id}&limit=1')
        if not rows: raise ValueError('unknown artifact')
        a=rows[0]
        raw=self.request('GET','/storage/v1/object/'+urllib.parse.quote(self.bucket)+'/'+a['object_key'])
        if hashlib.sha256(raw).hexdigest()!=a['sha256']: raise StorageError('Artifact integrity mismatch')
        return raw,a
