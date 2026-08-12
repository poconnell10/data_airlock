-- Multi-tenant customers + per-property feeds (Property Setup v2).
-- Applied remotely already; kept here for local/dev parity.

create table if not exists public.customers (
  id uuid primary key default gen_random_uuid(),
  customer_code varchar not null unique,
  customer_name varchar not null,
  created_at timestamptz default now()
);

alter table public.properties
  add column if not exists customer_id uuid references public.customers (id) on delete set null;

create table if not exists public.property_feeds (
  id uuid primary key default gen_random_uuid(),
  property_id varchar references public.properties (property_id) on delete cascade,
  feed_category varchar not null
    check (feed_category in ('pos', 'pms', 'res', 'lake', 'dwh')),
  preset_id varchar not null,
  schedule varchar,
  sla_cutoff_time time,
  s3_prefix varchar not null,
  active_contract_id uuid references public.ingestion_contracts (id) on delete set null,
  created_at timestamptz default now(),
  constraint uq_property_feed unique (property_id, feed_category, preset_id)
);

alter table public.customers enable row level security;
alter table public.property_feeds enable row level security;

do $$ begin
  create policy "Allow read access to all users"
    on public.customers for select to public using (true);
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "Allow write access to service role"
    on public.customers for all to public using (true) with check (true);
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "Allow read access to all users"
    on public.property_feeds for select to public using (true);
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "Allow write access to service role"
    on public.property_feeds for all to public using (true) with check (true);
exception when duplicate_object then null;
end $$;
