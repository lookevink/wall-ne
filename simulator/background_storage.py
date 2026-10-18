"""Durable local outbox; cloud replication never runs on the control thread.

Each session has one SQLite WAL and one FIFO sender. Immutable batches retain
writer/fence/batch IDs across retries. Runtime closure does not stop replication.
"""
from contextlib import contextmanager
import gzip
import hashlib
import json
import pathlib
import sqlite3
import threading
import time

from .common import canonical,uid,digest
from .persistence import Repository,StorageError

ROOT=pathlib.Path(__file__).resolve().parent.parent/'.runtime'/'outbox'
REGISTRY={}
RECOVERY_ERRORS={}
RESTORE_CONTEXT=threading.local()
REGISTRY_LOCK=threading.Lock()


class LocalArtifactMissing(LookupError):
    pass


class BackgroundRepository:
    def __init__(self,remote,root=ROOT,autostart=True):
        self.remote=remote;self.root=pathlib.Path(root);self.autostart=autostart
        self.db=None;self.session=None;self.lock=threading.RLock();self.wake=threading.Event()
        self.error=None;self.cloud_sequence=0;self.queued_sequence=0;self.last_lease=float("-inf")

    def __getattr__(self,name):return getattr(self.remote,name)

    def _open(self,session,lease=None):
        self.session=session;self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(self.root/(session+'.sqlite')),check_same_thread=False)
        self.db.execute('pragma journal_mode=WAL');self.db.execute('pragma synchronous=FULL')
        self.db.executescript('''create table if not exists metadata(key text primary key,value text not null);
            create table if not exists artifacts(id text primary key,metadata text not null,bytes blob not null);
            create table if not exists queue(id integer primary key autoincrement,kind text not null,payload text not null);
        ''')
        if lease is not None:
            with self.db:
                for key,value in dict(session=session,writer=self.remote.writer,url=self.remote.url,bucket=self.remote.bucket,lease=lease,cloud_sequence=lease['sequence'],queued_sequence=lease['sequence']).items():self._meta(key,value)
        meta={k:json.loads(v) for k,v in self.db.execute('select key,value from metadata')}
        if meta['url']!=self.remote.url or meta['bucket']!=self.remote.bucket:raise StorageError('Outbox belongs to a different backend')
        self.remote.writer=meta['writer'];self.remote.leases[session]=meta['lease']
        self.cloud_sequence=meta['cloud_sequence'];self.queued_sequence=meta['queued_sequence']
        with REGISTRY_LOCK:REGISTRY[session]=self
        if self.autostart:threading.Thread(target=self._run,daemon=True,name='outbox-'+session[:8]).start()

    def _meta(self,key,value):
        self.db.execute('insert or replace into metadata values(?,?)',(key,canonical(value)))

    def create(self,world,config):
        lease=self.remote.create(world,config)
        try:self._open(world.id,lease)
        except (OSError,sqlite3.Error):raise StorageError('Local outbox initialization failed') from None
        return lease

    def lease(self,session):
        # The sender renews remotely. The controller needs only its pinned fence.
        if session==self.session:return dict(self.remote.leases[session],sequence=self.queued_sequence)
        raise StorageError('Bind the background repository before restoring')

    def artifact(self,session,robot,kind,data,metadata):
        if session!=self.session:raise StorageError('Outbox session mismatch')
        raw=data if isinstance(data,bytes) else gzip.compress(canonical(data).encode(),mtime=0)
        sha=hashlib.sha256(raw).hexdigest();ext='png' if kind=='frame' else 'json.gz'
        artifact=dict(id=uid(),session_id=session,robot_id=robot,kind=kind,object_key=f'{session}/{kind}/{sha}.{ext}',sha256=sha,metadata=metadata,ready=True)
        try:
            with self.lock,self.db:
                self.db.execute('insert into artifacts values(?,?,?)',(artifact['id'],canonical(artifact),raw))
                self.db.execute('insert into queue(kind,payload) values(?,?)',('artifact',canonical(artifact)))
        except sqlite3.Error:raise StorageError('Local artifact persistence failed') from None
        self.wake.set();return artifact

    def commit(self,batch):
        try:
            with self.lock,self.db:
                if batch['expected_sequence']!=self.queued_sequence:raise StorageError('Local outbox sequence conflict')
                self.db.execute('insert into queue(kind,payload) values(?,?)',('commit',canonical(batch)))
                self._meta('queued_sequence',batch['sequence'])
            self.queued_sequence=batch['sequence']
        except sqlite3.Error:raise StorageError('Local checkpoint persistence failed') from None
        self.wake.set();return dict(sequence=batch['sequence'],revision=batch['revision'])

    def status(self):
        with self.lock:
            pending=self.db.execute('select count(*) from queue').fetchone()[0] if self.db else 0
        return dict(mode='background',pending_operations=pending,queued_sequence=self.queued_sequence,
                    cloud_committed_sequence=self.cloud_sequence,error=self.error,synced=pending==0 and self.cloud_sequence==self.queued_sequence)

    def local_artifact(self,artifact_id):
        with self.lock:row=self.db.execute('select bytes,metadata from artifacts where id=?',(artifact_id,)).fetchone() if self.db else None
        if row is None:raise LocalArtifactMissing('unknown local artifact')
        raw,meta=row;meta=json.loads(meta)
        if hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise StorageError('Local artifact integrity mismatch')
        return raw,meta

    def drain_one(self):
        with self.lock:row=self.db.execute('select id,kind,payload from queue order by id limit 1').fetchone()
        if row is None:return False
        ident,kind,payload=row;payload=json.loads(payload)
        if kind=='artifact':
            raw,artifact=self.local_artifact(payload['id'])
            result=self.remote.artifact(self.session,artifact['robot_id'],artifact['kind'],raw,artifact['metadata'])
            if result['sha256']!=artifact['sha256'] or result['object_key']!=artifact['object_key']:raise StorageError('Outbox artifact integrity mismatch')
        else:
            if time.monotonic()-self.last_lease>10:
                rows=self.remote.read('sessions',f'id=eq.{self.session}&select=writer,fence&limit=1')
                if not rows or rows[0]['writer']!=self.remote.writer or rows[0]['fence']!=payload['fence']:raise StorageError('Outbox writer fenced; reconciliation required')
                lease=self.remote.lease(self.session)
                if lease['fence']!=payload['fence']:raise StorageError('Outbox writer fenced; reconciliation required')
                self.last_lease=time.monotonic()
            result=self.remote.commit(payload)
            if result['sequence']!=payload['sequence']:raise StorageError('Outbox acknowledgement mismatch')
        # Remove only after an acknowledgement. An uncertain response replays the
        # original idempotent operation; never skip a failed row or change fence.
        with self.lock,self.db:
            self.db.execute('delete from queue where id=?',(ident,))
            if kind=='commit':self._meta('cloud_sequence',payload['sequence']);self.cloud_sequence=payload['sequence']
        self.error=None
        return True

    def _run(self):
        while True:
            try:
                if self.drain_one():continue
                self.wake.wait(1);self.wake.clear()
            except (StorageError,OSError,sqlite3.Error):
                self.error='Background sync failed; local evidence retained and retrying'
                self.wake.wait(2);self.wake.clear()
            except Exception:
                self.error='Background sync needs attention; local evidence retained'
                self.wake.wait(5);self.wake.clear()


def recover_outboxes(remote,root=ROOT):
    """Resume delivery only: never resume robot physics or paid inference."""
    recovered=[]
    if not remote.url or not remote.key:return recovered
    for path in pathlib.Path(root).glob('*.sqlite'):
        with REGISTRY_LOCK:existing=REGISTRY.get(path.stem)
        if existing:continue
        repo=BackgroundRepository(Repository(remote.url,remote.key),root)
        try:
            repo._open(path.stem);recovered.append(repo)
        except (StorageError,OSError,sqlite3.Error,KeyError,ValueError):
            if repo.db:repo.db.close()
            RECOVERY_ERRORS[path.stem]='Outbox recovery needs attention; local file retained'
    return recovered


def sync_status():
    with REGISTRY_LOCK:repos=list(REGISTRY.values())
    sessions={r.session:r.status() for r in repos}
    return dict(pending_operations=sum(s['pending_operations'] for s in sessions.values()),
                synced=not RECOVERY_ERRORS and all(s['synced'] for s in sessions.values()),sessions=sessions,recovery_errors=dict(RECOVERY_ERRORS))


def ensure_cloud_restore_safe():
    if getattr(RESTORE_CONTEXT,'active',False):return
    if not sync_status()['synced']:raise StorageError('Local background evidence is still syncing; restore is blocked to prevent stale-state replay')


def local_restart_checkpoint(repository,session):
    """Read the newest durable state after the local controller has exited.

    Used only for a new linked startup continuation. The original outbox and
    writer are untouched and keep replicating their immutable evidence.
    """
    with REGISTRY_LOCK:existing=REGISTRY.get(session)
    if existing is None:raise StorageError('Restart source has no local ownership record')
    with existing.lock:
        expected=existing.queued_sequence
        row=existing.db.execute("select payload from queue where kind='commit' order by id desc limit 1").fetchone()
        if row:
            batch=json.loads(row[0]);state=batch['state']
            if batch['session_id']!=session or batch['sequence']!=expected or batch['integrity_hash']!=digest(state):
                raise StorageError('Local restart checkpoint integrity mismatch')
        else:state=None
    if state is None:state=repository.restore(session)
    if state['id']!=session or state['seq']!=expected:
        raise StorageError('Restart checkpoint is behind local durable progress')
    return state


def bind_for_restore(repository,session):
    """Reuse the sole sender only after all local evidence has reached cloud."""
    ensure_cloud_restore_safe()
    with REGISTRY_LOCK:existing=REGISTRY.get(session)
    if existing:
        # No queued batch is rewritten. An explicit restore reacquires ownership
        # only after replication has drained, before reading the cloud checkpoint.
        if not existing.status()['synced']:raise StorageError('Session evidence is still syncing')
        lease=existing.remote.lease(session)
        with existing.lock,existing.db:
            if existing.db.execute('select count(*) from queue').fetchone()[0]:raise StorageError('New local evidence arrived during restore')
            existing._meta('lease',lease);existing._meta('cloud_sequence',lease['sequence']);existing._meta('queued_sequence',lease['sequence'])
            existing.cloud_sequence=existing.queued_sequence=lease['sequence']
        existing.remote.leases[session]=lease;existing.last_lease=time.monotonic()
        return existing
    remote=repository.remote if isinstance(repository,BackgroundRepository) else repository
    if not isinstance(remote,Repository):return repository
    repo=BackgroundRepository(Repository(remote.url,remote.key))
    lease=repo.remote.lease(session);repo._open(session,lease)
    return repo


@contextmanager
def cloud_restore_scope():
    """Check preexisting fleet evidence once; allow this restore's own new batches."""
    ensure_cloud_restore_safe()
    previous=getattr(RESTORE_CONTEXT,'active',False);RESTORE_CONTEXT.active=True
    try:yield
    finally:RESTORE_CONTEXT.active=previous
