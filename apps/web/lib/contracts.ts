export interface RangeRule {
  column_name: string;
  min_value: number | null;
  max_value: number | null;
}

export interface ContractFormState {
  propertyId: string;
  propertyName: string;
  vendorTemplate: string;
  timezone: string;
  slaCutoff: string;
  s3Bucket: string;
  s3Prefix: string;
  gracePeriodMinutes: number;
  slackWebhook: string;
  emailRecipients: string;
  filenameRegex: string;
  pathRegex: string;
  encoding: string;
  delimiter: string;
  headerPatterns: string;
  footerPatterns: string;
  ignorePatterns: string;
  declaredLineCountRegex: string;
  isMultiFileAtomicSet: boolean;
  requiredSetEndpoints: string[];
  contractVersion: string;
  fileFormat: string;
  // Gate 2
  maxZScore: number;
  enforceDowBaseline: boolean;
  frozenDateThresholdDays: number;
  // Gate 3
  requiredColumns: string[];
  nonNullColumns: string[];
  numericRanges: RangeRule[];
  // Gate 4
  headerVsLineBalance: boolean;
  salesVsTenderBalance: boolean;
  maxVariance: number;
}

function splitPatterns(raw: string): string[] {
  return raw
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Build ingestion contract JSONB document from Property Setup form state. */
export function buildContractDocument(
  state: ContractFormState
): Record<string, unknown> {
  return {
    profile_id: state.vendorTemplate,
    profile_version: state.contractVersion,
    description: `Airlock contract for ${state.propertyId}`,
    filename: {
      transport: "filename",
      // Engine (Python re) requires (?P<name>...); UI may store (?<name>...)
      pattern: state.filenameRegex.replace(/\(\?</g, "(?P<"),
      path_regex: state.pathRegex || null,
      path_pattern: state.pathRegex || null,
      required_groups: ["property", "report_type", "date"],
      date_format: "%Y%m%d",
    },
    file_format: {
      type: state.fileFormat || "delimited_text",
      encoding: state.encoding,
      delimiter: state.delimiter || null,
      line_ending: "\n",
    },
    physical: {
      encoding: state.encoding,
      delimiter: state.delimiter || null,
      line_ending: "lf",
      compression: "none",
      allow_bom: false,
      min_bytes: 1,
    },
    row_classification: {
      header_rules: splitPatterns(state.headerPatterns).map((pattern, i) => ({
        rule_id: `hdr_${i + 1}`,
        pattern,
      })),
      footer_rules: splitPatterns(state.footerPatterns).map((pattern, i) => ({
        rule_id: `ftr_${i + 1}`,
        pattern,
      })),
      ignore_rules: splitPatterns(state.ignorePatterns).map((pattern, i) => ({
        rule_id: `ign_${i + 1}`,
        pattern,
      })),
      row_count_declaration: state.declaredLineCountRegex
        ? {
            pattern: state.declaredLineCountRegex,
            compares_to: "total_read_rows",
          }
        : null,
    },
    atomic_set: {
      is_multi_file: state.isMultiFileAtomicSet,
      required_endpoints: state.requiredSetEndpoints,
    },
    atomic_sets: state.isMultiFileAtomicSet
      ? [
          {
            set_id: `${state.vendorTemplate}_atomic`,
            members: state.requiredSetEndpoints,
            group_by: ["property", "date"],
            applies_to_report_types: state.requiredSetEndpoints,
          },
        ]
      : [],
    gate_1: {
      is_multi_file_atomic_set: state.isMultiFileAtomicSet,
      required_set_endpoints: state.requiredSetEndpoints,
    },
    gate_2: {
      max_z_score: state.maxZScore,
      enforce_dow_baseline: state.enforceDowBaseline,
      frozen_date_threshold_days: state.frozenDateThresholdDays,
    },
    gate_3: {
      required_columns: state.requiredColumns,
      non_null_columns: state.nonNullColumns,
      numeric_ranges: state.numericRanges.map((r) => ({
        column_name: r.column_name,
        min_value: r.min_value,
        max_value: r.max_value,
      })),
    },
    gate_4: {
      header_vs_line_balance: state.headerVsLineBalance,
      sales_vs_tender_balance: state.salesVsTenderBalance,
      max_variance: state.maxVariance,
    },
  };
}

/** Build a minimal Opera-style sample payload for dry-run when no file uploaded. */
export function buildSyntheticSamplePayload(opts: {
  propertyId: string;
  reportType: string;
  businessDateIso: string;
  delimiter: string;
  dataRows?: number;
}): string {
  const d = opts.delimiter || "|";
  const rows = Math.max(1, opts.dataRows ?? 3);
  const lines: string[] = [
    `HDR${d}FILE${d}opera_v5${d}${opts.reportType}${d}${opts.propertyId}${d}${opts.businessDateIso}${d}`,
    `HDR${d}COLUMNS${d}col1${d}col2${d}col3${d}col4`,
  ];
  for (let i = 1; i <= rows; i += 1) {
    lines.push(
      `DAT${d}${opts.propertyId}${d}${opts.businessDateIso}${d}row${i}${d}ok`
    );
  }
  const total = lines.length + 1; // include trailer
  lines.push(`TRL${d}COUNT${d}${total}`);
  return lines.join("\n") + "\n";
}

export function parseEndpointList(raw: string): string[] {
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function parseTagList(raw: string): string[] {
  return raw
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
}
