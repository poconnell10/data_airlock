/**
 * Airlock contract persistence via FastAPI engine.
 */
import { getEngineUrl } from "@/lib/engine";
import type { AirlockContractV2 } from "@/lib/contracts/schema";
import type { FeedCategory, FeedContractForm } from "@/app/properties/setup/types";

export interface SaveAirlockContractInput {
  propertyId: string;
  feedId: string;
  feedCategory: FeedCategory | string;
  systemPreset: string;
  fileFormat: string;
  /** GitOps v2 document */
  contractV2: AirlockContractV2;
  /** Engine-compatible JSON used by Gates 1–4 */
  engineContract: Record<string, unknown>;
  /** Property / feed SLA fields to sync */
  timezone?: string;
  slaCutoff?: string;
  graceMinutes?: number;
  alertEmails?: string[];
  slackChannel?: string;
  existingContractId?: string | null;
  form?: FeedContractForm;
}

export interface SaveAirlockContractResult {
  id: string;
  property_id: string;
  feed_id: string;
  status: string;
  version: string;
  updated_at: string;
  ingestion_contract_id?: string | null;
  contract_yaml: AirlockContractV2 | Record<string, unknown>;
}

async function parseError(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const j = JSON.parse(text) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
    if (j.detail != null) return JSON.stringify(j.detail);
  } catch {
    /* plain text */
  }
  return text || `HTTP ${res.status}`;
}

/**
 * Persist the active setup form as a published airlock contract.
 * POST /api/v1/airlock/contracts → upsert airlock_contracts (+ ingestion sync).
 */
export async function saveAirlockContract(
  input: SaveAirlockContractInput
): Promise<SaveAirlockContractResult> {
  let res: Response;
  try {
    res = await fetch(`${getEngineUrl()}/api/v1/airlock/contracts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        property_id: input.propertyId,
        feed_id: input.feedId,
        feed_category: input.feedCategory,
        system_preset: input.systemPreset,
        file_format: input.fileFormat,
        contract_yaml: input.contractV2,
        engine_contract: input.engineContract,
        timezone: input.timezone,
        sla_cutoff_time: input.slaCutoff,
        grace_period_minutes: input.graceMinutes,
        alert_emails: input.alertEmails,
        slack_channel: input.slackChannel,
        existing_ingestion_contract_id: input.existingContractId ?? undefined,
      }),
    });
  } catch (e) {
    throw new Error(
      e instanceof Error
        ? `Engine unreachable: ${e.message}`
        : "Engine unreachable — is the FastAPI server running?"
    );
  }

  if (!res.ok) {
    throw new Error(
      `Save contract failed (${res.status}): ${await parseError(res)}`
    );
  }
  return (await res.json()) as SaveAirlockContractResult;
}

export async function fetchAirlockContract(
  propertyId: string,
  feedId: string
): Promise<SaveAirlockContractResult | null> {
  let res: Response;
  try {
    res = await fetch(
      `${getEngineUrl()}/api/v1/airlock/contracts/${encodeURIComponent(propertyId)}/${encodeURIComponent(feedId)}`
    );
  } catch {
    return null;
  }
  if (res.status === 404) return null;
  if (!res.ok) return null;
  return (await res.json()) as SaveAirlockContractResult;
}
