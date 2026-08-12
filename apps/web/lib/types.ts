export type OverallOutcome =
  | "PASS"
  | "FLAG"
  | "QUARANTINE_FILE"
  | "REJECT_FILE"
  | "HOLD_SET";

export interface SubEvaluation {
  rule_name: string;
  passed: boolean;
  message: string;
  details?: Record<string, unknown>;
}

export interface Gate1Report {
  overall_outcome: OverallOutcome;
  outcome_reason: string;
  filename_tokens: {
    report_type?: string | null;
    property?: string | null;
    date?: string | null;
    hash?: string | null;
  };
  evaluations: SubEvaluation[];
  total_rows: number;
  bytes_read: number;
}

export interface Gate2Report {
  overall_outcome: OverallOutcome;
  outcome_reason: string;
  evaluations: SubEvaluation[];
  z_score: number | null;
  baseline_mean: number | null;
  baseline_std: number | null;
  baseline_n: number;
}

export interface Gate3Report {
  overall_outcome: OverallOutcome;
  outcome_reason: string;
  evaluations: SubEvaluation[];
}

export interface Gate4Report {
  overall_outcome: OverallOutcome;
  outcome_reason: string;
  evaluations: SubEvaluation[];
  header_total: number | null;
  line_sum: number | null;
  net_sales: number | null;
  tender_payments: number | null;
  max_variance: number;
}

export interface DryRunReport {
  run_id: string;
  timestamp: string;
  property_id: string;
  filename: string;
  path: string | null;
  overall_outcome: OverallOutcome;
  outcome_reason: string;
  gate1_report: Gate1Report;
  gate2_report: Gate2Report;
  gate3_report: Gate3Report;
  gate4_report: Gate4Report;
  contract_profile_id?: string | null;
  contract_version?: string | number | null;
}

export interface SchemaInferenceResult {
  detected_format: string;
  inferred_delimiter: string | null;
  inferred_encoding: string;
  total_sample_lines: number;
  header_count: number;
  sample_headers: string[];
  suggested_filename_pattern: string;
  suggested_tokens: Record<string, string>;
  byte_length?: number;
  notes?: string[];
}

export interface AlertRules {
  slack_webhook_url?: string;
  email_recipients?: string[];
  notify_on?: string[];
}

export interface IngestionContractRow {
  id: string;
  profile_id: string;
  version: string;
  file_format: string;
  contract_yaml: Record<string, unknown>;
  description: string | null;
}

export interface PropertyRow {
  id: string;
  property_id: string;
  name?: string;
  property_name?: string;
  active?: boolean;
  vendor_template?: string | null;
  active_contract_id: string | null;
  s3_bucket: string;
  s3_prefix?: string;
  s3_prefix_pattern?: string;
  local_timezone?: string;
  timezone?: string;
  sla_delivery_cutoff?: string;
  sla_cutoff_time?: string;
  grace_period_minutes?: number;
  sla_grace_period_mins?: number;
  alert_rules?: AlertRules;
  alert_emails?: string[];
  slack_channel?: string;
}
