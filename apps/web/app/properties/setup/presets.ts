import type { FeedCategory, FeedContractForm, FeedMode } from "./types";

/** JS `(?<name>...)` → Python `(?P<name>...)` for engine contracts. */
export function toPythonNamedGroups(rawPattern: string): string {
  // Avoid double-converting already-Python groups: (?P< is not matched by (?< alone
  // after the ? because P intervenes — only bare (?< is rewritten.
  return rawPattern.replace(/\(\?</g, "(?P<");
}

/** Python `(?P<name>...)` → JS `(?<name>...)` for browser RegExp. */
export function toJsNamedGroups(rawPattern: string): string {
  return rawPattern.replace(/\(\?P</g, "(?<");
}

export interface CategoryDef {
  id: FeedCategory;
  name: string;
  full: string;
  mode: FeedMode;
}

export interface PresetDef {
  id: string;
  cat: FeedCategory;
  name: string;
  note: string;
  defaults: Partial<FeedContractForm> & {
    atomicList?: string[];
  };
}

export const FEED_CATEGORIES: CategoryDef[] = [
  { id: "pos", name: "POS", full: "Point of Sale", mode: "file" },
  { id: "pms", name: "PMS", full: "Property Management", mode: "file" },
  { id: "res", name: "Reservations", full: "Reservations Engine", mode: "file" },
  { id: "lake", name: "Data Lake", full: "S3 / GCS / Blob", mode: "object" },
  { id: "dwh", name: "Data Warehouse", full: "Snowflake / BigQuery", mode: "object" },
];

export const SYSTEM_PRESETS: PresetDef[] = [
  {
    id: "onesait",
    cat: "pos",
    name: "One Sait POS",
    note: "Pipe-delimited POS extract with an EOF trailer and a three-file atomic set.",
    defaults: {
      delimiter: "|",
      lineEnding: "\r\n",
      encoding: "UTF-8",
      filenameRegex:
        "^(?<report_type>[a-z_]+)_(?<property>[A-Z]{4}\\.[A-Z]{5})_(?<date>\\d{4}-\\d{2}-\\d{2})__(?<hash>[a-f0-9]+)\\.csv$",
      sampleFilename: "sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
      atomicList: ["headers_data", "sales_data", "payments_data"],
      isAtomic: true,
      headerPatterns: "^check_id\\|",
      footerPatterns: "^EOF",
      maxZScore: 3,
      maxVariance: 0.01,
    },
  },
  {
    id: "simphony",
    cat: "pos",
    name: "Micros Simphony",
    note: "Oracle Simphony check-detail export. Two files per business date.",
    defaults: {
      delimiter: ",",
      lineEnding: "\r\n",
      encoding: "Windows-1252",
      filenameRegex:
        "^(?<property>[A-Z]{4}\\.[A-Z]{5})_(?<report_type>[A-Za-z]+)_(?<date>\\d{8})\\.csv$",
      sampleFilename: "ESMA.MALAG_CheckDetail_20260809.csv",
      atomicList: ["CheckDetail", "TenderMedia"],
      isAtomic: true,
      headerPatterns: "^CheckNum,",
      footerPatterns: "",
      maxZScore: 3,
      maxVariance: 0.02,
    },
  },
  {
    id: "toast",
    cat: "pos",
    name: "Toast POS",
    note: "Toast API drop, UTF-8, one file per endpoint per day.",
    defaults: {
      delimiter: ",",
      lineEnding: "\n",
      encoding: "UTF-8",
      filenameRegex:
        "^(?<property>[a-z\\-]+)_(?<report_type>[A-Za-z]+)_(?<date>\\d{4}-\\d{2}-\\d{2})\\.csv$",
      sampleFilename: "soho-rooms_OrderDetails_2026-08-09.csv",
      atomicList: ["OrderDetails", "PaymentDetails"],
      isAtomic: true,
      headerPatterns: "^orderId,",
      maxZScore: 3.5,
      maxVariance: 0.01,
    },
  },
  {
    id: "customcsv",
    cat: "pos",
    name: "Custom CSV",
    note: "No vendor profile — every rule starts from platform defaults.",
    defaults: {
      delimiter: ",",
      encoding: "UTF-8",
      filenameRegex:
        "^(?<report_type>[a-z_]+)_(?<property>[A-Z0-9.]+)_(?<date>\\d{4}-\\d{2}-\\d{2})\\.csv$",
      sampleFilename: "sales_data_ESMA.MALAG_2026-08-09.csv",
      isAtomic: false,
      atomicList: [],
    },
  },
  {
    id: "opera",
    cat: "pms",
    name: "Opera V5 PMS",
    note: "Single nightly file, comma-delimited. Overlap drift matters more than volume.",
    defaults: {
      delimiter: ",",
      encoding: "ISO-8859-1",
      filenameRegex:
        "^(?<property>[A-Z]{4}\\.[A-Z]{5})_(?<report_type>[A-Z_]+)_(?<date>\\d{8})\\.txt$",
      sampleFilename: "ESMA.MALAG_STAT_DAILY_20260809.txt",
      atomicList: ["stat_daily"],
      isAtomic: true,
      headerPatterns: "^RESV_NAME_ID,",
      maxZScore: 2.5,
      maxVariance: 0.05,
    },
  },
  {
    id: "mews",
    cat: "pms",
    name: "Mews",
    note: "Mews Connector export. Reservations are mutable for ~30 days.",
    defaults: {
      delimiter: ",",
      encoding: "UTF-8",
      filenameRegex:
        "^(?<property>[a-z\\-]+)-(?<report_type>[a-z]+)-(?<date>\\d{4}-\\d{2}-\\d{2})\\.csv$",
      sampleFilename: "malaga-eurobuilding-reservations-2026-08-09.csv",
      atomicList: ["reservations", "folios"],
      isAtomic: true,
      headerPatterns: "^reservation_id,",
      maxZScore: 3.5,
    },
  },
  {
    id: "cloudbeds",
    cat: "pms",
    name: "Cloudbeds",
    note: "API-sourced CSV drop, UTF-8 with BOM.",
    defaults: {
      delimiter: ",",
      encoding: "UTF-8-BOM",
      filenameRegex:
        "^(?<property>[a-z\\-]+)-(?<report_type>[a-z]+)-(?<date>\\d{4}-\\d{2}-\\d{2})\\.csv$",
      sampleFilename: "malaga-eurobuilding-reservations-2026-08-09.csv",
      atomicList: ["reservations", "folios"],
      isAtomic: true,
    },
  },
  {
    id: "customtxt",
    cat: "pms",
    name: "Custom Text",
    note: "Fixed-width or bespoke delimited text.",
    defaults: {
      delimiter: "|",
      encoding: "UTF-8",
      filenameRegex:
        "^(?<property>[A-Z0-9.]+)_(?<report_type>[A-Z_]+)_(?<date>\\d{8})\\.txt$",
      isAtomic: false,
      atomicList: [],
    },
  },
  {
    id: "synxis",
    cat: "res",
    name: "SynXis",
    note: "Channel booking extract — volume is spiky by nature.",
    defaults: {
      delimiter: ",",
      encoding: "UTF-8",
      filenameRegex:
        "^(?<report_type>[a-z]+)_(?<property>[A-Z]{4}\\.[A-Z]{5})_(?<date>\\d{4}-\\d{2}-\\d{2})\\.csv$",
      sampleFilename: "bookings_ESMA.MALAG_2026-08-09.csv",
      atomicList: ["bookings"],
      isAtomic: true,
      maxZScore: 4,
    },
  },
  {
    id: "siteminder",
    cat: "res",
    name: "SiteMinder",
    note: "Channel manager delivery, one file per day.",
    defaults: {
      delimiter: ",",
      encoding: "UTF-8",
      filenameRegex:
        "^(?<property>[A-Z]{4}\\.[A-Z]{5})-(?<report_type>[a-z]+)-(?<date>\\d{4}-\\d{2}-\\d{2})\\.csv$",
      atomicList: ["reservations"],
      isAtomic: true,
      maxZScore: 4,
    },
  },
  {
    id: "customres",
    cat: "res",
    name: "Custom Feed",
    note: "Bespoke reservations feed.",
    defaults: {
      delimiter: ",",
      encoding: "UTF-8",
      isAtomic: false,
      atomicList: [],
      maxZScore: 4,
    },
  },
  {
    id: "s3parquet",
    cat: "lake",
    name: "S3 Parquet Landing",
    note: "Partitioned Parquet — identity from path; read after _SUCCESS.",
    defaults: {
      objectFormat: "Parquet",
      partitionKey: "business_date",
      watermarkColumn: "_ingested_at",
      partitionPath: "raw/{property}/{feed}/dt={date}/",
      requireCommitMarker: true,
    },
  },
  {
    id: "delta",
    cat: "lake",
    name: "Delta Lake Stream",
    note: "Delta table with transactional commits.",
    defaults: {
      objectFormat: "Delta",
      partitionKey: "business_date",
      watermarkColumn: "_commit_timestamp",
      partitionPath: "raw/{property}/{feed}/_delta_log/",
      requireCommitMarker: true,
    },
  },
  {
    id: "customjson",
    cat: "lake",
    name: "Custom JSON",
    note: "Newline-delimited JSON objects.",
    defaults: {
      objectFormat: "JSONL",
      partitionKey: "dt",
      watermarkColumn: "ingested_at",
      partitionPath: "raw/{property}/{feed}/dt={date}/",
      requireCommitMarker: false,
    },
  },
  {
    id: "snowflake",
    cat: "dwh",
    name: "Snowflake Stage",
    note: "External stage unloaded per business date.",
    defaults: {
      objectFormat: "Parquet",
      partitionKey: "business_date",
      watermarkColumn: "_unloaded_at",
      partitionPath: "stage/{property}/{feed}/dt={date}/",
      requireCommitMarker: true,
      maxZScore: 2.5,
    },
  },
  {
    id: "bigquery",
    cat: "dwh",
    name: "BigQuery Export",
    note: "Scheduled table export to GCS.",
    defaults: {
      objectFormat: "Avro",
      partitionKey: "business_date",
      watermarkColumn: "_export_time",
      partitionPath: "export/{property}/{feed}/dt={date}/",
      requireCommitMarker: true,
      maxZScore: 2.5,
    },
  },
];

export function categoryOf(id: string): CategoryDef {
  return FEED_CATEGORIES.find((c) => c.id === id) ?? FEED_CATEGORIES[0];
}

export function presetOf(id: string): PresetDef | undefined {
  return SYSTEM_PRESETS.find((p) => p.id === id);
}

export function presetsForCategory(cat: FeedCategory): PresetDef[] {
  return SYSTEM_PRESETS.filter((p) => p.cat === cat);
}

export function isFileCategory(cat: FeedCategory): boolean {
  return categoryOf(cat).mode === "file";
}

export function defaultPrefix(propertyId: string, cat: FeedCategory): string {
  return `s3://ing-airlock/raw/${propertyId}/${cat}/`;
}

export function emptyForm(partial?: Partial<FeedContractForm>): FeedContractForm {
  return {
    timezone: "Europe/Madrid",
    cutoff: "07:00",
    graceMinutes: 60,
    ledgerBackfill: true,
    ledgerWeekend: true,
    encoding: "UTF-8",
    delimiter: ",",
    lineEnding: "\n",
    filenameRegex:
      "^(?<report_type>[a-z_]+)_(?<property>[A-Z0-9.]+)_(?<date>\\d{4}-\\d{2}-\\d{2})\\.csv$",
    sampleFilename: "sales_data_ESMA.MALAG_2026-08-09.csv",
    headerPatterns: "",
    footerPatterns: "",
    ignorePatterns: "^\\s*$\n.DS_Store\n*.tmp",
    declaredCountRegex: "",
    pathAgree: true,
    isAtomic: false,
    atomicMembers: "",
    objectFormat: "Parquet",
    partitionKey: "business_date",
    watermarkColumn: "_ingested_at",
    partitionPath: "raw/{property}/{feed}/dt={date}/",
    requireCommitMarker: true,
    maxZScore: 3,
    enforceDow: true,
    frozenWindow: true,
    headerVsLine: true,
    salesVsTender: true,
    maxVariance: 0.01,
    alertEmails: "",
    slackChannel: "#data-ops-alerts",
    manifestPrefix: "s3://ing-airlock/reports/",
    ...partial,
  };
}

export function formFromPreset(
  presetId: string,
  base?: Partial<FeedContractForm>
): FeedContractForm {
  const p = presetOf(presetId);
  const d = p?.defaults ?? {};
  const { atomicList, ...rest } = d;
  return emptyForm({
    ...base,
    ...rest,
    atomicMembers: (atomicList ?? []).join(", "),
    isAtomic: Boolean(atomicList?.length),
  });
}

export function buildFeedContractYaml(
  form: FeedContractForm,
  opts: {
    propertyId: string;
    feedCategory: FeedCategory;
    presetId: string;
    s3Prefix: string;
  }
): Record<string, unknown> {
  const file = isFileCategory(opts.feedCategory);
  const members = form.atomicMembers
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const doc: Record<string, unknown> = {
    profile_id: opts.presetId,
    feed_category: opts.feedCategory,
    landing_prefix: opts.s3Prefix,
    schedule: {
      timezone: form.timezone,
      sla_cutoff_time: form.cutoff,
      grace_period_minutes: form.graceMinutes,
      accept_late_backfill: form.ledgerBackfill,
      expect_seven_days: form.ledgerWeekend,
    },
    gate_2: {
      max_z_score: form.maxZScore,
      enforce_dow_baseline: form.enforceDow,
      frozen_date_threshold_days: form.frozenWindow ? 30 : 3650,
    },
    gate_4: {
      header_vs_line_balance: form.headerVsLine,
      sales_vs_tender_balance: form.salesVsTender,
      max_variance: form.maxVariance,
    },
    alerts: {
      email_recipients: form.alertEmails
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      slack_channel: form.slackChannel,
      manifest_prefix: form.manifestPrefix,
    },
  };

  if (file) {
    doc.filename = {
      pattern: toPythonNamedGroups(form.filenameRegex),
      required_groups: ["property", "report_type", "date"],
      path_agree: form.pathAgree,
    };
    doc.file_format = {
      type: "delimited_text",
      encoding: form.encoding.toLowerCase().replace("utf-8-bom", "utf-8-sig"),
      delimiter: form.delimiter,
      line_ending: form.lineEnding === "\r\n" ? "crlf" : "lf",
    };
    doc.row_classification = {
      header_patterns: form.headerPatterns.split("\n").filter(Boolean),
      footer_patterns: form.footerPatterns.split("\n").filter(Boolean),
      ignore_patterns: form.ignorePatterns.split("\n").filter(Boolean),
      row_count_declaration: form.declaredCountRegex
        ? { pattern: toPythonNamedGroups(form.declaredCountRegex) }
        : null,
    };
    doc.atomic_set = {
      is_multi_file: form.isAtomic,
      required_endpoints: members,
    };
  } else {
    doc.object_landing = {
      format: form.objectFormat,
      partition_key: form.partitionKey,
      watermark_column: form.watermarkColumn,
      partition_path: form.partitionPath,
      require_commit_marker: form.requireCommitMarker,
      commit_marker: "_SUCCESS",
    };
    doc.file_format = {
      type: form.objectFormat.toLowerCase(),
      encoding: "utf-8",
    };
  }

  return doc;
}
