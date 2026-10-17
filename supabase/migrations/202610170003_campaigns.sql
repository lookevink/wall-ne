create table public.evaluation_campaigns (
 id uuid primary key, baseline_id uuid references public.prompt_versions(id), candidate_id uuid unique references public.prompt_versions(id),
 manifest jsonb not null, status text not null, results jsonb not null, reason text not null,
 created_at timestamptz not null default now()
);
alter table public.evaluation_campaigns enable row level security;
revoke all on public.evaluation_campaigns from anon,authenticated;
grant all on public.evaluation_campaigns to service_role;
create or replace function public.wallne_manifest_immutable() returns trigger language plpgsql as $$ begin
 if new.manifest<>old.manifest or new.baseline_id<>old.baseline_id or new.candidate_id<>old.candidate_id then raise exception 'campaign manifest is frozen'; end if;
 return new;
end $$;
create trigger wallne_frozen_manifest before update on public.evaluation_campaigns for each row execute function public.wallne_manifest_immutable();
