-- Per-feed published Airlock contracts (Property Setup save / GitOps export).
-- Unique on (property_id, feed_id); mirrors engine-compatible JSON into
-- ingestion_contracts so Gates 1–4 keep reading the active feed contract.

create table if not exists public.airlock_contracts (
  id uuid primary key default gen_random_uuid(),
  property_id text not null references public.properties (property_id) on delete cascade,
  feed_id uuid not null references public.property_feeds (id) on delete cascade,
  feed_category text,
  system_preset text not null,
  status text not null default 'published'
    check (status in ('draft', 'published')),
  version text not null default '2.0',
  contract_yaml jsonb not null
    check (jsonb_typeof(contract_yaml) = 'object'),
  engine_contract jsonb not null default '{}'::jsonb
    check (jsonb_typeof(engine_contract) = 'object'),
  ingestion_contract_id uuid references public.ingestion_contracts (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint airlock_contracts_property_feed_uniq unique (property_id, feed_id)
);

create index if not exists airlock_contracts_property_id_idx
  on public.airlock_contracts (property_id);

create index if not exists airlock_contracts_feed_id_idx
  on public.airlock_contracts (feed_id);

create index if not exists airlock_contracts_status_idx
  on public.airlock_contracts (status);

comment on table public.airlock_contracts is
  'Published per-feed Airlock contracts (v2 GitOps schema + engine JSON).';

drop trigger if exists airlock_contracts_set_updated_at on public.airlock_contracts;
create trigger airlock_contracts_set_updated_at
  before update on public.airlock_contracts
  for each row
  execute function public.set_updated_at();

alter table public.airlock_contracts enable row level security;

do $$ begin
  create policy "Anon can select airlock_contracts"
    on public.airlock_contracts for select
    to anon
    using (true);
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "Anon can insert airlock_contracts"
    on public.airlock_contracts for insert
    to anon
    with check (true);
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "Anon can update airlock_contracts"
    on public.airlock_contracts for update
    to anon
    using (true)
    with check (true);
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "Authenticated users can select airlock_contracts"
    on public.airlock_contracts for select
    to authenticated
    using (true);
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "Authenticated users can insert airlock_contracts"
    on public.airlock_contracts for insert
    to authenticated
    with check (true);
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "Authenticated users can update airlock_contracts"
    on public.airlock_contracts for update
    to authenticated
    using (true)
    with check (true);
exception when duplicate_object then null;
end $$;
