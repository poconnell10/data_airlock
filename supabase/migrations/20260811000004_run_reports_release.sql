-- Persist / release support for adjudication queue.
-- Adds feed_category + release audit columns; allows RELEASED_TO_ETL outcome;
-- permits UPDATE only for operator release transitions.

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
    'MISSING_DELIVERY',
    'RELEASED_TO_ETL'
  ]::text[]));

alter table public.run_reports
  add column if not exists feed_category text;

alter table public.run_reports
  add column if not exists released_by text;

alter table public.run_reports
  add column if not exists released_at timestamptz;

alter table public.run_reports
  add column if not exists findings jsonb default '[]'::jsonb;

create index if not exists run_reports_feed_category_idx
  on public.run_reports (feed_category);

create index if not exists run_reports_outcome_feed_idx
  on public.run_reports (overall_outcome, feed_category);

-- Allow release updates: only overall_outcome → RELEASED_TO_ETL plus release audit fields.
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

    raise exception 'run_reports are immutable; updates and deletes are not allowed';
  end if;

  return new;
end;
$$;

comment on column public.run_reports.feed_category is
  'pos|pms|res|lake|dwh — denormalized from property_feeds / contract for queue filters.';
comment on column public.run_reports.released_by is
  'Operator id that approved RELEASED_TO_ETL.';
