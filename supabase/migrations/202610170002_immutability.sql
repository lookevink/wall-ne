create or replace function public.wallne_immutable() returns trigger language plpgsql as $$ begin raise exception 'evidence is append-only'; end $$;
DO $$ declare t text; begin
 foreach t in array array['events','actions','checkpoints','artifacts','reviews','evaluations','prompt_activations'] loop
  -- Reviews permit linking a single candidate through the controlled RPC added below.
  if t <> 'reviews' then
   execute format('create trigger wallne_append_only before update or delete on public.%I for each row execute function public.wallne_immutable()',t);
  end if;
 end loop;
end $$;
create or replace function public.wallne_prompt_immutable() returns trigger language plpgsql as $$ begin
 if new.text<>old.text or new.hash<>old.hash or new.role<>old.role or new.parent_id is distinct from old.parent_id then raise exception 'prompt contents are immutable'; end if;
 return new;
end $$;
create trigger wallne_prompt_contents before update on public.prompt_versions for each row execute function public.wallne_prompt_immutable();
create or replace function public.wallne_candidate(p_candidate jsonb,p_review uuid) returns jsonb language plpgsql security definer set search_path=public as $$
declare r reviews; p prompt_versions; begin
 select * into strict r from reviews where id=p_review for update;
 if r.candidate_id is not null then raise exception 'one candidate per review'; end if;
 select * into strict p from prompt_versions where id=(p_candidate->>'parent_id')::uuid;
 if p.role<>p_candidate->>'role' then raise exception 'parent role mismatch'; end if;
 insert into prompt_versions(id,role,text,hash,parent_id,source_review,status) values((p_candidate->>'id')::uuid,p_candidate->>'role',p_candidate->>'text',p_candidate->>'hash',p.id,p_review,'candidate');
 update reviews set candidate_id=(p_candidate->>'id')::uuid where id=p_review;
 return p_candidate;
end $$;
revoke all on function public.wallne_candidate(jsonb,uuid) from public,anon,authenticated;
grant execute on function public.wallne_candidate(jsonb,uuid) to service_role;
