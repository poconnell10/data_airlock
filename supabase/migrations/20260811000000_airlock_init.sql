-- Data Airlock Suite — initial schema
-- Stores ingestion contracts (profile YAMLs as JSONB), property metadata,
-- and immutable Gate 1–4 run reports for audit + Day-of-Week baselines.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- ingestion_contracts: versioned PMS profile YAMLs as queryable JSONB
-- ---------------------------------------------------------------------------
create table if not exists public.ingestion_contracts (
  id uuid primary key default gen_random_uuid(),
  profile_id text not null,
  version text not null,
  file_format text not null,
  contract_yaml jsonb not null,
  description text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ingestion_contracts_profile_version_uniq unique (profile_id, version),
  constraint ingestion_contracts_yaml_is_object check (jsonb_typeof(contract_yaml) = 'object')
);

create index if not exists ingestion_contracts_profile_id_idx
  on public.ingestion_contracts (profile_id);

create index if not exists ingestion_contracts_file_format_idx
  on public.ingestion_contracts (file_format);

comment on table public.ingestion_contracts is
  'Versioned ingestion contracts; profile YAML stored as JSONB for queryability.';

-- ---------------------------------------------------------------------------
-- properties: hotel property metadata + S3/R2 landing config + alert rules
-- ---------------------------------------------------------------------------
create table if not exists public.properties (
  id uuid primary key default gen_random_uuid(),
  property_id text not null unique,
  name text not null,
  active boolean not null default true,
  vendor_template text,
  active_contract_id uuid references public.ingestion_contracts (id) on delete set null,
  s3_bucket text not null,
  s3_prefix text not null default '',
  local_timezone text not null default 'UTC',
  sla_delivery_cutoff time not null default '06:00:00',
  grace_period_minutes integer not null default 30
    check (grace_period_minutes >= 0),
  alert_rules jsonb not null default '{}'::jsonb,
  -- alert_rules shape:
  -- {
  --   "slack_webhook_url": "https://hooks.slack.com/...",
  --   "email_recipients": ["ops@example.com"],
  --   "notify_on": ["REJECT_FILE", "QUARANTINE_FILE", "HOLD_SET"]
  -- }
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint properties_alert_rules_is_object check (jsonb_typeof(alert_rules) = 'object')
);

create index if not exists properties_active_contract_id_idx
  on public.properties (active_contract_id);

create index if not exists properties_active_idx
  on public.properties (active);

comment on table public.properties is
  'Hotel properties with S3/R2 landing prefixes, SLA cutoffs, and alert routing.';

comment on column public.properties.alert_rules is
  'JSONB alert config: slack_webhook_url, email_recipients, notify_on outcomes.';

-- ---------------------------------------------------------------------------
-- run_reports: immutable Gate 1–4 execution logs
-- Used for audit trails and Gate 2 30-day Day-of-Week z-score baselines.
-- ---------------------------------------------------------------------------
create table if not exists public.run_reports (
  id uuid primary key default gen_random_uuid(),
  run_id text not null unique,
  property_id text not null references public.properties (property_id) on delete restrict,
  report_type text not null,
  business_date date not null,
  day_of_week smallint not null
    check (day_of_week between 0 and 6), -- 0 = Sunday … 6 = Saturday (ISO-adjacent; Sunday=0)
  overall_outcome text not null
    check (overall_outcome in (
      'PASS', 'FLAG', 'QUARANTINE_FILE', 'REJECT_FILE', 'HOLD_SET'
    )),
  outcome_reason text,
  gate_results jsonb not null default '[]'::jsonb,
  row_accounting jsonb not null default '{}'::jsonb,
  file_identity jsonb not null default '{}'::jsonb,
  accepted_rows integer,
  raw_report jsonb not null,
  executed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint run_reports_immutable_no_update check (true)
);

-- Composite index for Gate 2 baseline queries:
-- 30-day Day-of-Week z-scores filtered by property / report type / outcome.
create index if not exists run_reports_baseline_idx
  on public.run_reports (
    property_id,
    report_type,
    day_of_week,
    overall_outcome,
    business_date desc
  );

create index if not exists run_reports_executed_at_idx
  on public.run_reports (executed_at desc);

comment on table public.run_reports is
  'Immutable Gate 1–4 run reports for audit and statistical baselines.';

-- ---------------------------------------------------------------------------
-- updated_at trigger helper
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists ingestion_contracts_set_updated_at on public.ingestion_contracts;
create trigger ingestion_contracts_set_updated_at
  before update on public.ingestion_contracts
  for each row execute function public.set_updated_at();

drop trigger if exists properties_set_updated_at on public.properties;
create trigger properties_set_updated_at
  before update on public.properties
  for each row execute function public.set_updated_at();

-- Prevent mutations on run_reports (immutability)
create or replace function public.prevent_run_report_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'run_reports are immutable; updates and deletes are not allowed';
end;
$$;

drop trigger if exists run_reports_no_update on public.run_reports;
create trigger run_reports_no_update
  before update or delete on public.run_reports
  for each row execute function public.prevent_run_report_mutation();

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table public.ingestion_contracts enable row level security;
alter table public.properties enable row level security;
alter table public.run_reports enable row level security;

-- Authenticated operators can read/write contracts and properties.
create policy "Authenticated users can select ingestion_contracts"
  on public.ingestion_contracts for select
  to authenticated
  using (true);

create policy "Authenticated users can insert ingestion_contracts"
  on public.ingestion_contracts for insert
  to authenticated
  with check (true);

create policy "Authenticated users can update ingestion_contracts"
  on public.ingestion_contracts for update
  to authenticated
  using (true)
  with check (true);

create policy "Authenticated users can select properties"
  on public.properties for select
  to authenticated
  using (true);

create policy "Authenticated users can insert properties"
  on public.properties for insert
  to authenticated
  with check (true);

create policy "Authenticated users can update properties"
  on public.properties for update
  to authenticated
  using (true)
  with check (true);

-- Run reports: insert + select only (immutable after write).
create policy "Authenticated users can select run_reports"
  on public.run_reports for select
  to authenticated
  using (true);

create policy "Authenticated users can insert run_reports"
  on public.run_reports for insert
  to authenticated
  with check (true);

-- Service role bypasses RLS by default; no explicit service policies needed.
