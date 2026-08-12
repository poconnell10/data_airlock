import { getEngineUrl } from "@/lib/api/dryRun";

export type JournalNoteType =
  | "DECISION_REASON"
  | "MEETING_REQUIRED"
  | "VENDOR_ESCALATION"
  | "THRESHOLD_ADJUSTMENT"
  | "NOTE_ADDED";

export type CustomerImpact =
  | "NONE"
  | "LOW"
  | "MEDIUM"
  | "HIGH"
  | "CUSTOMER_NOTIFIED";

export type LifecycleEvent =
  | "OVERRIDE_RELEASE"
  | "FILE_REJECTED"
  | "THRESHOLD_TUNED"
  | "VENDOR_TICKET_OPENED"
  | "NOTE_ADDED"
  | "RELEASE_OVERRIDE"
  | "HARD_REJECT"
  | "CONTRACT_THRESHOLD_TUNED";

export type PropertyJournalEntry = {
  journal_id: string;
  property_id: string;
  run_id?: string | null;
  gate_number?: number | null;
  rule_id?: string | null;
  operator_id: string;
  note_type: JournalNoteType | string;
  customer_impact: CustomerImpact | string;
  lifecycle_event: LifecycleEvent | string;
  content: string;
  report_type?: string | null;
  created_at: string;
};

export async function fetchPropertyJournal(
  propertyId: string,
  opts?: {
    note_type?: string;
    customer_impact?: string;
    limit?: number;
    offset?: number;
  }
): Promise<PropertyJournalEntry[]> {
  const params = new URLSearchParams();
  if (opts?.note_type) params.set("note_type", opts.note_type);
  if (opts?.customer_impact) params.set("customer_impact", opts.customer_impact);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString();
  const url = `${getEngineUrl()}/api/v1/properties/${encodeURIComponent(
    propertyId
  )}/journal${qs ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to load journal (${res.status})`);
  }
  return (await res.json()) as PropertyJournalEntry[];
}

export async function createPropertyJournalEntry(
  propertyId: string,
  body: {
    operator_id: string;
    content: string;
    note_type?: JournalNoteType;
    customer_impact?: CustomerImpact;
    lifecycle_event?: LifecycleEvent;
    run_id?: string;
    report_type?: string;
  }
): Promise<PropertyJournalEntry> {
  const res = await fetch(
    `${getEngineUrl()}/api/v1/properties/${encodeURIComponent(
      propertyId
    )}/journal`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to create journal entry (${res.status})`);
  }
  return (await res.json()) as PropertyJournalEntry;
}

export async function postRunAuditNote(
  runId: string,
  body: {
    operator_id: string;
    content: string;
    note_type?: JournalNoteType;
    gate_number?: number;
    rule_id?: string;
  }
): Promise<{ success: boolean; note_id: string; journal_projected: boolean }> {
  const res = await fetch(
    `${getEngineUrl()}/api/v1/airlock/runs/${encodeURIComponent(
      runId
    )}/audit-notes`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to save audit note (${res.status})`);
  }
  return (await res.json()) as {
    success: boolean;
    note_id: string;
    journal_projected: boolean;
  };
}
