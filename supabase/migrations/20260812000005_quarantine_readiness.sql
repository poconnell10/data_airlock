-- Quarantine readiness metrics + operator classification on run_reports.

alter table public.run_reports
  add column if not exists readiness_stats jsonb default '{"total_rows":0,"verified_rows":0,"quarantined_rows":0,"readiness_pct":100.0,"quarantine_pct":0.0}'::jsonb;

alter table public.run_reports
  add column if not exists quarantine_manifest jsonb default '[]'::jsonb;

comment on column public.run_reports.readiness_stats is
  'Processing readiness: total/verified/quarantined rows + percentages.';
comment on column public.run_reports.quarantine_manifest is
  'Per-rule quarantine diagnostics with suggested/user categories.';

-- Allow release OR operator classification updates (manifest / readiness only).
create or replace function public.prevent_run_report_mutation()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'run_reports are immutable; deletes are not allowed';
  end if;

  if tg_op = 'UPDATE' then
    -- Operator release: blocked/flagged → RELEASED_TO_ETL
    if new.overall_outcome = 'RELEASED_TO_ETL'
       and old.overall_outcome in ('HOLD_SET', 'QUARANTINE_FILE', 'FLAG', 'REJECT_FILE')
       and new.run_id is not distinct from old.run_id
       and new.property_id is not distinct from old.property_id
       and new.report_type is not distinct from old.report_type
       and new.business_date is not distinct from old.business_date
    then
      return new;
    end if;

    -- Operator re-classification: same identity/outcome; only diagnostic fields change
    if new.overall_outcome is not distinct from old.overall_outcome
       and new.run_id is not distinct from old.run_id
       and new.property_id is not distinct from old.property_id
       and new.report_type is not distinct from old.report_type
       and new.business_date is not distinct from old.business_date
       and new.checksum_sha256 is not distinct from old.checksum_sha256
    then
      return new;
    end if;

    raise exception 'run_reports are immutable; updates and deletes are not allowed';
  end if;

  return new;
end;
$$;
