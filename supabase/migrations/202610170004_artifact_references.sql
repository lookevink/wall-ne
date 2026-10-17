-- Several observations may share identical immutable bytes while retaining distinct capture metadata.
alter table public.artifacts drop constraint if exists artifacts_object_key_key;
create index if not exists artifacts_object_key on public.artifacts(object_key);
