-- Property Journal & run audit notes.
-- Dual-write: inserts into run_audit_notes project into property_journal_entries.

-- ---------------------------------------------------------------------------
-- run_audit_notes: per-run operator notes (source of truth for sync trigger)
-- ---------------------------------------------------------------------------
create table if not exists public.run_audit_notes (
  note_id uuid primary key default gen_random_uuid(),
  run_id text not null references public.run_reports (run_id) on delete cascade,
  gate_number integer,
  rule_id text,
  operator_id text not null,
  note_type text not null
    check (note_type in (
      'DECISION_REASON',
      'MEETING_REQUIRED',
      'VENDOR_ESCALATION',
      'THRESHOLD_ADJUSTMENT',
      'NOTE_ADDED'
    )),
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists run_audit_notes_run_id_idx
  on public.run_audit_notes (run_id, created_at desc);

comment on table public.run_audit_notes is
  'Operator audit notes attached to a Gate evaluation run.';

-- ---------------------------------------------------------------------------
-- property_journal_entries: property-level long-term operational timeline
-- ---------------------------------------------------------------------------
create table if not exists public.property_journal_entries (
  journal_id uuid primary key default gen_random_uuid(),
  property_id text not null,
  run_id text references public.run_reports (run_id) on delete set null,
  gate_number integer,
  rule_id text,
  operator_id text not null,
  note_type text not null
    check (note_type in (
      'DECISION_REASON',
      'MEETING_REQUIRED',
      'VENDOR_ESCALATION',
      'THRESHOLD_ADJUSTMENT',
      'NOTE_ADDED'
    )),
  customer_impact text not null default 'NONE'
    check (customer_impact in (
      'NONE',
      'LOW',
      'MEDIUM',
      'HIGH',
      'CUSTOMER_NOTIFIED'
    )),
  lifecycle_event text not null
    check (lifecycle_event in (
      'OVERRIDE_RELEASE',
      'FILE_REJECTED',
      'THRESHOLD_TUNED',
      'VENDOR_TICKET_OPENED',
      'NOTE_ADDED',
      'RELEASE_OVERRIDE',
      'HARD_REJECT',
      'CONTRACT_THRESHOLD_TUNED'
    )),
  content text not null,
  report_type text,
  created_at timestamptz not null default now()
);

create index if not exists idx_property_journal_property
  on public.property_journal_entries (property_id, created_at desc);

create index if not exists idx_property_journal_note_type
  on public.property_journal_entries (property_id, note_type, created_at desc);

create index if not exists idx_property_journal_impact
  on public.property_journal_entries (property_id, customer_impact, created_at desc);

comment on table public.property_journal_entries is
  'Unified property-level journal for decisions, escalations, and sync notes.';

-- ---------------------------------------------------------------------------
-- Trigger: mirror run_audit_notes → property_journal_entries
-- ---------------------------------------------------------------------------
create or replace function public.fn_sync_audit_note_to_journal()
returns trigger
language plpgsql
as $$
declare
  v_property_id text;
  v_report_type text;
begin
  select property_id, report_type
    into v_property_id, v_report_type
  from public.run_reports
  where run_id = new.run_id;

  insert into public.property_journal_entries (
    property_id,
    run_id,
    gate_number,
    rule_id,
    operator_id,
    note_type,
    customer_impact,
    lifecycle_event,
    content,
    report_type,
    created_at
  ) values (
    coalesce(v_property_id, 'UNKNOWN'),
    new.run_id,
    new.gate_number,
    new.rule_id,
    new.operator_id,
    new.note_type,
    case
      when new.note_type = 'VENDOR_ESCALATION' then 'CUSTOMER_NOTIFIED'
      when new.note_type = 'DECISION_REASON' then 'LOW'
      else 'NONE'
    end,
    'NOTE_ADDED',
    new.content,
    v_report_type,
    coalesce(new.created_at, now())
  );

  return new;
end;
$$;

drop trigger if exists trg_sync_audit_note_to_journal on public.run_audit_notes;

create trigger trg_sync_audit_note_to_journal
after insert on public.run_audit_notes
for each row
execute function public.fn_sync_audit_note_to_journal();

-- ---------------------------------------------------------------------------
-- RLS (engine uses service role; anon policies mirror setup control-plane)
-- ---------------------------------------------------------------------------
alter table public.run_audit_notes enable row level security;
alter table public.property_journal_entries enable row level security;

create policy "Anon can select run_audit_notes"
  on public.run_audit_notes for select
  to anon
  using (true);

create policy "Anon can insert run_audit_notes"
  on public.run_audit_notes for insert
  to anon
  with check (true);

create policy "Anon can select property_journal_entries"
  on public.property_journal_entries for select
  to anon
  using (true);

create policy "Anon can insert property_journal_entries"
  on public.property_journal_entries for insert
  to anon
  with check (true);
