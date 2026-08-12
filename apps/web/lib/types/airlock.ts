/** Shared Airlock execution / quarantine diagnostic types. */

export type QuarantineCategory =
  | "DATA_QUALITY_BUG"
  | "OVERLAP_DRIFT"
  | "DUPLICATE_PAYLOAD"
  | "VENDOR_CONFIG_CHANGE"
  | "UNMAPPED_ENTITY"
  | "UNBALANCED_REVENUE"
  | "BUSINESS_EDGE_CASE"
  | "FALSE_POSITIVE"
  | "FROZEN_PERIOD_ATTEMPT";

export const QUARANTINE_CATEGORIES: QuarantineCategory[] = [
  "DATA_QUALITY_BUG",
  "OVERLAP_DRIFT",
  "DUPLICATE_PAYLOAD",
  "VENDOR_CONFIG_CHANGE",
  "UNMAPPED_ENTITY",
  "UNBALANCED_REVENUE",
  "BUSINESS_EDGE_CASE",
  "FALSE_POSITIVE",
  "FROZEN_PERIOD_ATTEMPT",
];

export interface ReadinessStats {
  total_rows: number;
  verified_rows: number;
  quarantined_rows: number;
  readiness_pct: number;
  quarantine_pct: number;
}

export interface QuarantineManifestItem {
  rule_id: string;
  affected_rows: number;
  row_indices: number[];
  suggested_category: QuarantineCategory;
  user_category?: QuarantineCategory | null;
  user_notes?: string | null;
  message: string;
  sample_records: Record<string, unknown>[];
  is_file_level?: boolean;
  decision_guidance?: string;
}

export interface ExecutionRunReport {
  run_id: string;
  property_id: string;
  business_date: string;
  outcome: string;
  report_type?: string;
  feed_category?: string | null;
  readiness_stats: ReadinessStats;
  quarantine_manifest: QuarantineManifestItem[];
  findings?: Record<string, unknown>[];
  gate_evaluations?: Record<string, unknown>;
  s3_path?: string | null;
  outcome_reason?: string | null;
}

export function emptyReadinessStats(): ReadinessStats {
  return {
    total_rows: 0,
    verified_rows: 0,
    quarantined_rows: 0,
    readiness_pct: 100,
    quarantine_pct: 0,
  };
}

export function formatRowCount(n: number): string {
  return n.toLocaleString();
}
