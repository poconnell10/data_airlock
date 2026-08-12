import { getEngineUrl } from "@/lib/engine";
import type {
  QuarantineCategory,
  QuarantineManifestItem,
  ReadinessStats,
} from "@/lib/types/airlock";

export type OverrideType = "DECLARE_SHORT" | "REDRIVE_VALIDATION";

export type FeedCategoryFilter =
  | "ALL"
  | "POS"
  | "PMS"
  | "RESERVATIONS"
  | "DATA_LAKE"
  | "DATA_WAREHOUSE";

export type RunOutcomeFilter =
  | "ALL"
  | "HOLD_SET"
  | "QUARANTINE_FILE"
  | "REJECT_FILE"
  | "FLAGGED"
  | "RELEASED"
  | "RELEASED_TO_ETL";

export interface AdjudicationItem {
  run_id: string;
  property_id: string;
  property_name: string;
  report_type: string;
  business_date: string;
  overall_outcome: string;
  created_at: string;
  gate_evaluations: Record<string, unknown>;
  s3_path?: string | null;
  timezone?: string | null;
  outcome_reason?: string | null;
  feed_category?: string | null;
  released_by?: string | null;
  released_at?: string | null;
  readiness_stats?: ReadinessStats | null;
  quarantine_manifest?: QuarantineManifestItem[];
}

export interface AdjudicationMetrics {
  active_quarantines: number;
  held_sets: number;
  sla_breaches: number;
  overrides_executed_today: number;
  rejects?: number;
}

export interface OverrideRequest {
  run_id: string;
  property_id: string;
  override_type: OverrideType;
  reason: string;
  operator_id: string;
}

export interface OverrideResponse {
  success: boolean;
  new_run_id?: string | null;
  status?: string | null;
  override_type: string;
  message?: string;
  gate_report?: Record<string, unknown> | null;
}

export interface ReleaseRequest {
  operator_id: string;
  reason: string;
}

export interface ReleaseResponse {
  success: boolean;
  run_id: string;
  status: string;
  released_by?: string | null;
  released_at?: string | null;
  event?: string;
  message?: string;
}

/** Map UI filter pills → persisted feed_category values. */
export function feedCategoryMatches(
  itemCategory: string | null | undefined,
  filter: FeedCategoryFilter
): boolean {
  if (filter === "ALL") return true;
  const raw = (itemCategory || "").trim().toLowerCase();
  const aliases: Record<FeedCategoryFilter, string[]> = {
    ALL: [],
    POS: ["pos"],
    PMS: ["pms"],
    RESERVATIONS: ["res", "reservations"],
    DATA_LAKE: ["lake", "data_lake"],
    DATA_WAREHOUSE: ["dwh", "data_warehouse"],
  };
  return aliases[filter].includes(raw);
}

/** Map UI outcome pills → overall_outcome values (FLAGGED ↔ FLAG). */
export function outcomeMatches(
  outcome: string,
  filter: RunOutcomeFilter
): boolean {
  if (filter === "ALL") return true;
  if (filter === "FLAGGED") return outcome === "FLAG" || outcome === "FLAGGED";
  if (filter === "RELEASED") {
    return outcome === "PASS" || outcome === "PASS_OVERRIDDEN" || outcome === "RELEASED";
  }
  return outcome === filter;
}

export function filterAdjudicationItems(
  items: AdjudicationItem[],
  category: FeedCategoryFilter,
  outcome: RunOutcomeFilter
): AdjudicationItem[] {
  return items.filter(
    (item) =>
      feedCategoryMatches(item.feed_category, category) &&
      outcomeMatches(item.overall_outcome, outcome)
  );
}

export async function fetchAdjudicationQueue(): Promise<AdjudicationItem[]> {
  const res = await fetch(`${getEngineUrl()}/api/v1/adjudication/queue`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Queue load failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<AdjudicationItem[]>;
}

export async function fetchAdjudicationMetrics(): Promise<AdjudicationMetrics> {
  const res = await fetch(`${getEngineUrl()}/api/v1/adjudication/metrics`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Metrics load failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<AdjudicationMetrics>;
}

export async function submitOverride(
  payload: OverrideRequest
): Promise<OverrideResponse> {
  const res = await fetch(`${getEngineUrl()}/api/v1/adjudication/override`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Override failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<OverrideResponse>;
}

export async function releaseRun(
  runId: string,
  payload: ReleaseRequest
): Promise<ReleaseResponse> {
  const res = await fetch(
    `${getEngineUrl()}/api/v1/airlock/runs/${encodeURIComponent(runId)}/release`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Release failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<ReleaseResponse>;
}

export interface ClassifyPatch {
  rule_id: string;
  user_category: QuarantineCategory;
  user_notes?: string | null;
}

export interface ClassifyResponse {
  success: boolean;
  run_id: string;
  quarantine_manifest: QuarantineManifestItem[];
  message?: string;
}

export async function classifyRun(
  runId: string,
  operatorId: string,
  classifications: ClassifyPatch[]
): Promise<ClassifyResponse> {
  const res = await fetch(
    `${getEngineUrl()}/api/v1/airlock/runs/${encodeURIComponent(runId)}/classify`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operator_id: operatorId,
        classifications,
      }),
    }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Classify failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<ClassifyResponse>;
}

/** Pull high-signal failing detail keys from gate_evaluations. */
export function extractFailureHighlights(
  gates: Record<string, unknown>
): Array<{ key: string; value: unknown }> {
  const hits: Array<{ key: string; value: unknown }> = [];
  const interesting = new Set([
    "offending_byte",
    "error_start",
    "error_end",
    "missing_endpoints",
    "poison_value",
    "z_score",
    "variance",
    "failures",
  ]);

  const walk = (node: unknown, path: string) => {
    if (Array.isArray(node)) {
      node.forEach((item, idx) => walk(item, `${path}[${idx}]`));
      return;
    }
    if (!node || typeof node !== "object") return;
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      const next = path ? `${path}.${k}` : k;
      if (interesting.has(k) && v !== undefined && v !== null) {
        hits.push({ key: next, value: v });
      }
      if (k === "passed" && v === false) {
        const msg = (node as Record<string, unknown>).message;
        if (msg) hits.push({ key: `${next}/message`, value: msg });
      }
      if (typeof v === "object") walk(v, next);
    }
  };

  walk(gates, "");
  return hits.slice(0, 12);
}

const RULE_ALIASES: Record<string, string> = {
  sales_vs_tender_balance: "G4_FINANCIAL_IMBALANCE",
  header_vs_line_balance: "G4_FINANCIAL_IMBALANCE",
  physical_integrity: "G1_PHYSICAL_INTEGRITY",
  endpoint_registered: "G1_UNREGISTERED_ENDPOINT",
  non_empty_payload: "G1_EMPTY_PAYLOAD",
  numeric_column_integrity: "G3_TYPE_CAST_FAIL",
};

const CATEGORY_BY_RULE: Record<string, QuarantineCategory> = {
  G4_FINANCIAL_IMBALANCE: "UNBALANCED_REVENUE",
  G4_UNBALANCED_HEADER: "UNBALANCED_REVENUE",
  G4_ZERO_COVER_REVENUE: "BUSINESS_EDGE_CASE",
  G4_FULL_COMP: "BUSINESS_EDGE_CASE",
  G1_PHYSICAL_INTEGRITY: "DATA_QUALITY_BUG",
  G3_TYPE_CAST_FAIL: "DATA_QUALITY_BUG",
  G3_RAGGED_ROW: "DATA_QUALITY_BUG",
};

/** Rebuild quarantine manifest client-side from gate_evaluations when DB row is empty. */
export function buildManifestFromGateEvaluations(
  gates: Record<string, unknown>
): QuarantineManifestItem[] {
  const items: QuarantineManifestItem[] = [];
  const gateKeys = ["gate_1", "gate_2", "gate_3", "gate_4", "gate1", "gate2", "gate3", "gate4"];
  for (const key of Object.keys(gates)) {
    if (!gateKeys.includes(key) && !/^gate[_-]?\d$/i.test(key)) continue;
    const report = gates[key];
    if (!report || typeof report !== "object") continue;
    const blob = report as Record<string, unknown>;
    const evals = (blob.evaluations || blob.findings || []) as unknown[];
    if (!Array.isArray(evals)) continue;
    for (const raw of evals) {
      if (!raw || typeof raw !== "object") continue;
      const ev = raw as Record<string, unknown>;
      if (ev.passed === true) continue;
      const details =
        ev.details && typeof ev.details === "object"
          ? (ev.details as Record<string, unknown>)
          : {};
      if (details.skipped === true) continue;
      const rawName = String(
        ev.rule_name || ev.check_name || ev.rule_id || "UNKNOWN"
      );
      const message = String(ev.message || "");
      const ruleId =
        RULE_ALIASES[rawName] ||
        (rawName.toUpperCase().startsWith("G")
          ? rawName.toUpperCase()
          : RULE_ALIASES[rawName.toLowerCase()] || rawName);
      const suggested =
        CATEGORY_BY_RULE[ruleId] ||
        (/Financial imbalance|Net sales|Tender/i.test(message)
          ? "UNBALANCED_REVENUE"
          : "DATA_QUALITY_BUG");
      items.push({
        rule_id: ruleId === "sales_vs_tender_balance" ? "G4_FINANCIAL_IMBALANCE" : ruleId,
        affected_rows: 0,
        row_indices: [],
        suggested_category: suggested,
        message,
        sample_records: [],
        is_file_level: true,
        decision_guidance:
          suggested === "UNBALANCED_REVENUE"
            ? "Financial balance variance detected between sales and payments tender. Decide whether to declare short or reject payload."
            : message,
      });
    }
  }
  return items;
}
