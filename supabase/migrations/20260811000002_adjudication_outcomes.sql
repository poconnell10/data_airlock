-- Adjudication outcomes + optional object path for redrive workflows.
-- Extends run_reports for PASS_OVERRIDDEN / MISSING_DELIVERY audit rows.

alter table public.run_reports drop constraint if exists run_reports_overall_outcome_check;

alter table public.run_reports
  add constraint run_reports_overall_outcome_check
  check (overall_outcome::text = any (array[
    'PASS',
    'FLAG',
    'HOLD_SET',
    'QUARANTINE_FILE',
    'REJECT_FILE',
    'PASS_OVERRIDDEN',
    'MISSING_DELIVERY'
  ]::text[]));

alter table public.run_reports
  add column if not exists s3_path text;

alter table public.run_reports
  add column if not exists outcome_reason text;
