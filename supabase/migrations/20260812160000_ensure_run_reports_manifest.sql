-- Ensure quarantine_manifest exists on run_reports and refresh PostgREST cache.
-- Idempotent: safe if 20260812000005_quarantine_readiness.sql already applied.

alter table if exists public.run_reports
  add column if not exists quarantine_manifest jsonb default '[]'::jsonb;

alter table if exists public.run_reports
  add column if not exists readiness_stats jsonb default '{"total_rows":0,"verified_rows":0,"quarantined_rows":0,"readiness_pct":100.0,"quarantine_pct":0.0}'::jsonb;

comment on column public.run_reports.quarantine_manifest is
  'Per-rule quarantine diagnostics with suggested/user categories.';

notify pgrst, 'reload schema';
