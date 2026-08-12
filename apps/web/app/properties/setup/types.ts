/** Multi-tenant / multi-feed Property Setup v2 domain types. */

export type FeedCategory = "pos" | "pms" | "res" | "lake" | "dwh";

export type FeedMode = "file" | "object";

export interface Customer {
  id: string;
  customer_code: string;
  customer_name: string;
  created_at?: string | null;
}

export interface Property {
  id: string;
  property_id: string;
  property_name: string;
  customer_id: string | null;
  timezone: string | null;
  sla_cutoff_time: string | null;
  sla_grace_period_mins: number | null;
  alert_emails: string[] | null;
  slack_channel: string | null;
  active_contract_id: string | null;
  s3_bucket: string;
  s3_prefix_pattern: string;
  created_at?: string | null;
  updated_at?: string | null;
  customers?: Customer | null;
}

export interface PropertyFeed {
  id: string;
  property_id: string;
  feed_category: FeedCategory;
  preset_id: string;
  schedule: string | null;
  sla_cutoff_time: string | null;
  s3_prefix: string;
  active_contract_id: string | null;
  created_at?: string | null;
}

export interface IngestionContract {
  id: string;
  profile_id: string;
  version: number | string;
  file_format: string;
  contract_yaml: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PropertyWithFeeds extends Property {
  property_feeds: PropertyFeed[];
  customer?: Customer | null;
}

export interface CustomerTree extends Customer {
  properties: PropertyWithFeeds[];
}

export interface CreatePropertyInput {
  customerId?: string | null;
  customerName: string;
  customerCode?: string;
  propertyId: string;
  propertyName: string;
  timezone: string;
  feedCategory: FeedCategory;
  presetId: string;
  schedule: string;
  slaCutoff: string;
  s3Prefix?: string;
  s3Bucket?: string;
}

export interface CreateFeedInput {
  propertyId: string;
  feedCategory: FeedCategory;
  presetId: string;
  schedule: string;
  slaCutoff: string;
  s3Prefix?: string;
}

export interface SaveFeedContractInput {
  feedId: string;
  propertyId: string;
  profileId: string;
  fileFormat: string;
  contractYaml: Record<string, unknown>;
  existingContractId?: string | null;
  version?: number;
}

/** Editable contract form state for the selected feed. */
export interface FeedContractForm {
  // Schedule
  timezone: string;
  cutoff: string;
  graceMinutes: number;
  ledgerBackfill: boolean;
  ledgerWeekend: boolean;
  // File mode
  encoding: string;
  delimiter: string;
  lineEnding: string;
  filenameRegex: string;
  sampleFilename: string;
  headerPatterns: string;
  footerPatterns: string;
  ignorePatterns: string;
  declaredCountRegex: string;
  pathAgree: boolean;
  isAtomic: boolean;
  atomicMembers: string;
  // Object mode
  objectFormat: string;
  partitionKey: string;
  watermarkColumn: string;
  partitionPath: string;
  requireCommitMarker: boolean;
  // Gate 2–4
  maxZScore: number;
  enforceDow: boolean;
  frozenWindow: boolean;
  headerVsLine: boolean;
  salesVsTender: boolean;
  maxVariance: number;
  // Alerts
  alertEmails: string;
  slackChannel: string;
  manifestPrefix: string;
}
