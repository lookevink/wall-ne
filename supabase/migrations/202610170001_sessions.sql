-- Wall-ne service-only schema. No browser role may read checkpoints or write state.
create table if not exists public.sessions (
 id uuid primary key, kind text not null, seed integer not null, status text not null,
 metadata jsonb not null, committed_sequence bigint not null default 0,
 revision bigint not null default 0, resume_epoch integer not null default 0,
 writer uuid, fence bigint not null default 0, lease_until timestamptz,
 started_at timestamptz not null default now(), ended_at timestamptz,
 verification jsonb
);
create table if not exists public.robot_sessions (
 session_id uuid references public.sessions(id), robot_id text, sequence bigint not null,
 projection jsonb not null, heartbeat timestamptz not null default now(),
 primary key(session_id,robot_id)
);
create table if not exists public.actions (
 session_id uuid references public.sessions(id), command_id text, robot_id text,
 receipt jsonb not null, primary key(session_id,command_id)
);
create table if not exists public.events (
 session_id uuid references public.sessions(id), sequence bigint, robot_id text,
 revision bigint not null, resume_epoch integer not null, wall_utc timestamptz not null,
 sim_time double precision not null, type text not null, payload jsonb not null,
 primary key(session_id,sequence)
);
create index if not exists events_robot_time on public.events(session_id,robot_id,sequence);
create table if not exists public.checkpoints (
 session_id uuid references public.sessions(id), sequence bigint, revision bigint not null,
 state jsonb not null, integrity_hash text not null, primary key(session_id,sequence)
);
create table if not exists public.artifacts (
 id uuid primary key, session_id uuid references public.sessions(id), robot_id text,
 sequence bigint not null, kind text not null, object_key text not null unique,
 sha256 text not null, metadata jsonb not null, ready boolean not null default true
);
create index if not exists artifacts_session on public.artifacts(session_id,sequence);
create table if not exists public.commit_batches (
 session_id uuid references public.sessions(id), batch_id uuid, result jsonb not null,
 primary key(session_id,batch_id)
);
create table if not exists public.prompt_versions (
 id uuid primary key, role text not null, text text not null, hash text not null,
 parent_id uuid references public.prompt_versions(id), source_review uuid,
 status text not null default 'candidate', created_at timestamptz not null default now()
);
create table if not exists public.reviews (
 id uuid primary key, session_id uuid references public.sessions(id),
 evidence jsonb not null, diagnosis jsonb not null, candidate_id uuid references public.prompt_versions(id),
 created_at timestamptz not null default now()
);
create table if not exists public.evaluations (
 id uuid primary key, baseline_id uuid references public.prompt_versions(id), candidate_id uuid references public.prompt_versions(id),
 manifest jsonb not null, results jsonb not null, passed boolean not null default false,
 reason text not null, created_at timestamptz not null default now()
);
create table if not exists public.prompt_activations (
 id bigserial primary key, role text not null, version_id uuid references public.prompt_versions(id),
 evaluation_id uuid references public.evaluations(id), reason text not null, created_at timestamptz not null default now()
);
DO $$ declare t text; begin
 foreach t in array array['sessions','robot_sessions','actions','events','checkpoints','artifacts','commit_batches','prompt_versions','reviews','evaluations','prompt_activations'] loop
  execute format('alter table public.%I enable row level security', t);
  execute format('revoke all on public.%I from anon, authenticated',t);
  execute format('grant all on public.%I to service_role',t);
 end loop;
end $$;

create or replace function public.wallne_create(p_session jsonb) returns jsonb
language plpgsql security definer set search_path=public as $$
begin
 insert into sessions(id,kind,seed,status,metadata)
 values((p_session->>'id')::uuid,p_session->>'kind',(p_session->>'seed')::integer,'paused',p_session)
 on conflict(id) do nothing;
 return jsonb_build_object('id',p_session->>'id');
end $$;

create or replace function public.wallne_lease(p_session uuid,p_writer uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare s sessions; begin
 select * into strict s from sessions where id=p_session for update;
 if s.writer is distinct from p_writer and s.lease_until>now() then raise exception 'writer lease held'; end if;
 if s.writer is distinct from p_writer then s.fence=s.fence+1; s.resume_epoch=s.resume_epoch+1; end if;
 update sessions set writer=p_writer,fence=s.fence,resume_epoch=s.resume_epoch,lease_until=now()+interval '30 seconds' where id=p_session;
 return jsonb_build_object('fence',s.fence,'resume_epoch',s.resume_epoch,'sequence',s.committed_sequence);
end $$;

create or replace function public.wallne_commit(p_batch jsonb) returns jsonb
language plpgsql security definer set search_path=public as $$
declare s sessions; e jsonb; a jsonb; result jsonb; sid uuid=(p_batch->>'session_id')::uuid;
 last_seq bigint; bid uuid=(p_batch->>'batch_id')::uuid;
begin
 select * into strict s from sessions where id=sid for update;
 -- A stale writer cannot replay an old batch after its lease has been fenced.
 if s.writer is distinct from (p_batch->>'writer')::uuid or s.fence<>(p_batch->>'fence')::bigint or s.lease_until<now() then raise exception 'writer fenced'; end if;
 select b.result into result from commit_batches b where b.session_id=sid and b.batch_id=bid;
 if found then return result; end if;
 if s.committed_sequence<>(p_batch->>'expected_sequence')::bigint then raise exception 'sequence conflict'; end if;
 last_seq=s.committed_sequence;
 for e in select * from jsonb_array_elements(p_batch->'events') loop
  if (e->>'sequence')::bigint<>last_seq+1 then raise exception 'event sequence gap'; end if;
  last_seq=last_seq+1;
  insert into events values(sid,last_seq,e->>'robot_id',(e->>'revision')::bigint,s.resume_epoch,(e->>'wall_utc')::timestamptz,(e->>'sim_time')::double precision,e->>'type',e->'payload');
 end loop;
 if last_seq<>(p_batch->>'sequence')::bigint then raise exception 'checkpoint sequence mismatch'; end if;
 for a in select * from jsonb_array_elements(p_batch->'actions') loop
  insert into actions values(sid,a->>'command_id',a->>'robot_id',a) on conflict do nothing;
 end loop;
 for a in select * from jsonb_array_elements(p_batch->'robots') loop
  insert into robot_sessions values(sid,a->>'robot_id',(a->>'sequence')::bigint,a,now())
  on conflict(session_id,robot_id) do update set sequence=excluded.sequence,projection=excluded.projection,heartbeat=excluded.heartbeat
  where robot_sessions.sequence<excluded.sequence;
 end loop;
 for a in select * from jsonb_array_elements(p_batch->'artifacts') loop
  if not (a->>'ready')::boolean then raise exception 'artifact not durable'; end if;
  insert into artifacts values((a->>'id')::uuid,sid,a->>'robot_id',last_seq,a->>'kind',a->>'object_key',a->>'sha256',a->'metadata',true) on conflict(id) do nothing;
 end loop;
 insert into checkpoints values(sid,last_seq,(p_batch->>'revision')::bigint,p_batch->'state',p_batch->>'integrity_hash');
 update sessions set committed_sequence=last_seq,revision=(p_batch->>'revision')::bigint,status=p_batch->>'status',verification=p_batch->'verification',
  ended_at=case when p_batch->>'status' in ('completed','failed','aborted','blocked') then now() else null end,
  lease_until=now()+interval '30 seconds' where id=sid;
 result=jsonb_build_object('sequence',last_seq,'revision',p_batch->'revision');
 insert into commit_batches values(sid,bid,result);
 return result;
end $$;

create or replace function public.wallne_activate(p_version uuid,p_evaluation uuid,p_rollback boolean default false) returns jsonb
language plpgsql security definer set search_path=public as $$
declare v prompt_versions; ev evaluations; begin
 select * into strict v from prompt_versions where id=p_version;
 select * into strict ev from evaluations where id=p_evaluation;
 if not ev.passed or (not p_rollback and ev.candidate_id<>p_version) or (p_rollback and ev.baseline_id<>p_version) then raise exception 'passing evaluation required'; end if;
 perform pg_advisory_xact_lock(hashtext(v.role));
 update prompt_versions set status='retired' where role=v.role and status='active';
 update prompt_versions set status='active' where id=p_version;
 insert into prompt_activations(role,version_id,evaluation_id,reason) values(v.role,p_version,p_evaluation,case when p_rollback then 'rollback' else 'evaluated promotion' end);
 return jsonb_build_object('active',p_version);
end $$;
revoke all on function public.wallne_create(jsonb),public.wallne_lease(uuid,uuid),public.wallne_commit(jsonb),public.wallne_activate(uuid,uuid,boolean) from public,anon,authenticated;
grant execute on function public.wallne_create(jsonb),public.wallne_lease(uuid,uuid),public.wallne_commit(jsonb),public.wallne_activate(uuid,uuid,boolean) to service_role;
insert into storage.buckets(id,name,public) values('robot-session-artifacts','robot-session-artifacts',false) on conflict(id) do update set public=false;
