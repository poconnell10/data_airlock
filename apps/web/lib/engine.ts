/**
 * Engine client helpers.
 * Dry-run lives in `@/lib/api/dryRun` — re-exported here for existing imports.
 */
import type { SchemaInferenceResult } from "@/lib/types";
import {
  getEngineUrl,
  runAirlockDryRun as runDryRunApi,
  type RunAirlockDryRunInput,
} from "@/lib/api/dryRun";
import type { DryRunReport } from "@/lib/types";

export { getEngineUrl } from "@/lib/api/dryRun";
export {
  runAirlockDryRun as runAirlockDryRunForm,
  toVerdictLabel,
} from "@/lib/api/dryRun";

/** @deprecated Prefer `RunAirlockDryRunInput` from `@/lib/api/dryRun`. */
export interface DryRunPayload {
  property_id: string;
  filename: string;
  path?: string;
  s3_uri?: string;
  payload_text?: string;
  payload_b64?: string;
  fetch_uri?: boolean;
  present_batch_filenames?: string[];
  contract_yaml?: string;
  contract_json?: Record<string, unknown>;
}

/** Backward-compatible JSON dry-run wrapper used by older callers. */
export async function runAirlockDryRun(
  payload: DryRunPayload
): Promise<DryRunReport> {
  const input: RunAirlockDryRunInput = {
    propertyId: payload.property_id,
    file: null,
    // Only use multipart/S3 path when explicitly fetching a remote object.
    s3Key: payload.fetch_uri ? payload.s3_uri ?? null : null,
    filename: payload.filename,
    path: payload.path ?? payload.s3_uri,
    payloadText: payload.payload_text,
    presentBatchFilenames: payload.present_batch_filenames,
    contract: payload.contract_json ?? {},
    fetchUri: Boolean(payload.fetch_uri),
  };
  return runDryRunApi(input);
}

export async function inspectSampleFile(
  file: File
): Promise<SchemaInferenceResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("filename", file.name);

  const res = await fetch(`${getEngineUrl()}/api/v1/inference/inspect`, {
    method: "POST",
    body: form,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Inspect failed (${res.status}): ${text}`);
  }

  return res.json() as Promise<SchemaInferenceResult>;
}

export async function inspectS3Uri(
  s3Uri: string,
  filename?: string
): Promise<SchemaInferenceResult> {
  const form = new FormData();
  form.append("s3_uri", s3Uri);
  if (filename) form.append("filename", filename);

  const res = await fetch(`${getEngineUrl()}/api/v1/inference/inspect`, {
    method: "POST",
    body: form,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Inspect failed (${res.status}): ${text}`);
  }

  return res.json() as Promise<SchemaInferenceResult>;
}
