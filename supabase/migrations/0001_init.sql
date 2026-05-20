-- AI Vault initial schema
-- Two tables: bundles (groups of files owned by a user) and files (inline text content for V1).
-- RLS is owner-only; every policy gates on auth.uid() = owner_id.

create extension if not exists "pgcrypto";

create table if not exists public.bundles (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 120),
  description text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists bundles_owner_updated_idx
  on public.bundles (owner_id, updated_at desc);

-- For V1 file content lives inline in a text column. AI config files are small;
-- this keeps reads/writes one round-trip and avoids orphan blobs. storage_kind
-- is reserved so we can migrate large/binary files to Supabase Storage later
-- by switching to 'storage' and populating storage_path, without a schema break.
create table if not exists public.files (
  id uuid primary key default gen_random_uuid(),
  bundle_id uuid not null references public.bundles(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  path text not null check (char_length(path) between 1 and 512),
  content text not null default '',
  storage_kind text not null default 'inline' check (storage_kind in ('inline', 'storage')),
  storage_path text,
  size_bytes int not null default 0 check (size_bytes >= 0 and size_bytes <= 1048576),
  mime_type text not null default 'text/plain',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (bundle_id, path)
);

create index if not exists files_bundle_path_idx
  on public.files (bundle_id, path);

-- updated_at auto-touch
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists bundles_touch_updated_at on public.bundles;
create trigger bundles_touch_updated_at
  before update on public.bundles
  for each row execute function public.touch_updated_at();

drop trigger if exists files_touch_updated_at on public.files;
create trigger files_touch_updated_at
  before update on public.files
  for each row execute function public.touch_updated_at();

-- Bump parent bundle's updated_at when its files change.
create or replace function public.bump_bundle_updated_at()
returns trigger
language plpgsql
as $$
declare
  target_bundle uuid;
begin
  if (tg_op = 'DELETE') then
    target_bundle := old.bundle_id;
  else
    target_bundle := new.bundle_id;
  end if;

  update public.bundles
    set updated_at = now()
    where id = target_bundle;

  if (tg_op = 'DELETE') then
    return old;
  end if;
  return new;
end;
$$;

drop trigger if exists files_bump_bundle on public.files;
create trigger files_bump_bundle
  after insert or update or delete on public.files
  for each row execute function public.bump_bundle_updated_at();

-- RLS
alter table public.bundles enable row level security;
alter table public.files enable row level security;

drop policy if exists bundles_select_own on public.bundles;
create policy bundles_select_own on public.bundles
  for select using (auth.uid() = owner_id);

drop policy if exists bundles_insert_own on public.bundles;
create policy bundles_insert_own on public.bundles
  for insert with check (auth.uid() = owner_id);

drop policy if exists bundles_update_own on public.bundles;
create policy bundles_update_own on public.bundles
  for update using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

drop policy if exists bundles_delete_own on public.bundles;
create policy bundles_delete_own on public.bundles
  for delete using (auth.uid() = owner_id);

drop policy if exists files_select_own on public.files;
create policy files_select_own on public.files
  for select using (auth.uid() = owner_id);

-- Insert additionally checks the parent bundle is owned by the caller so a user
-- can't slip a file under another account's bundle even if they spoof owner_id.
drop policy if exists files_insert_own on public.files;
create policy files_insert_own on public.files
  for insert with check (
    auth.uid() = owner_id
    and exists (
      select 1 from public.bundles b
      where b.id = bundle_id and b.owner_id = auth.uid()
    )
  );

drop policy if exists files_update_own on public.files;
create policy files_update_own on public.files
  for update using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

drop policy if exists files_delete_own on public.files;
create policy files_delete_own on public.files
  for delete using (auth.uid() = owner_id);
