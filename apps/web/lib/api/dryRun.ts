import type { DryRunReport } from "@/lib/types";

const DEFAULT_ENGINE_URL = "http://localhost:8000";

export function getEngineUrl(): string {
  return (
    process.env.NEXT_PUBLIC_ENGINE_URL?.replace(/\/$/, "") || DEFAULT_ENGINE_URL
  );
}

/** Contract document sent to the engine (Gate1 + schedule / gate configs). */
export type DryRunContract = Record<string, unknown>;

export interface RunAirlockDryRunInput {
  propertyId: string;
  /** Uploaded file for local POC test bench (multipart). */
  file?: File | null;
  /** Landing object key or s3:// URI for production-style dry-runs. */
  s3Key?: string | null;
  /** Basename used when no File is provided. */
  filename?: string;
  /** Full path / URI shown in Gate 1 path-agreement. */
  path?: string;
  /** Inline sample when neither file nor S3 fetch is used. */
  payloadText?: string;
  presentBatchFilenames?: string[];
  /** Serialized Gate 1 / full airlock contract (UI CFG → YAML/JSON). */
  contract: DryRunContract;
  /** When true and s3Key is set, engine fetches remote bytes. */
  fetchUri?: boolean;
  /**
   * When true, POST /api/v1/airlock/evaluate with persist_run=true
   * (writes to run_reports / adjudication queue). Otherwise dry-run.
   */
  persistRun?: boolean;
  /** Optional feed category for persisted runs (pos|pms|res|lake|dwh). */
  feedCategory?: string | null;
}

export type VerdictLabel =
  | "RELEASED"
  | "FLAGGED"
  | "QUARANTINE"
  | "REJECT"
  | "HOLD_SET";

/** Map engine overall_outcome → bench verdict banner labels. */
export function toVerdictLabel(outcome: string): VerdictLabel {
  switch (outcome) {
    case "PASS":
      return "RELEASED";
    case "FLAG":
      return "FLAGGED";
    case "QUARANTINE_FILE":
      return "QUARANTINE";
    case "REJECT_FILE":
      return "REJECT";
    case "HOLD_SET":
      return "HOLD_SET";
    default:
      return "QUARANTINE";
  }
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
 * Run Gates 1–4 against an uploaded file, S3 key, or inline payload.
 *
 * Default: multipart `/dry-run/upload` or JSON `/dry-run`.
 * When persistRun=true: JSON `POST /evaluate` with `{ persist_run: true }`.
 */
export async function runAirlockDryRun(
  input: RunAirlockDryRunInput
): Promise<DryRunReport> {
  const {
    propertyId,
    file = null,
    s3Key = null,
    filename,
    path,
    payloadText,
    presentBatchFilenames = [],
    contract,
    fetchUri = Boolean(s3Key && !file),
    persistRun = false,
    feedCategory = null,
  } = input;

  const resolvedName =
    filename ||
    file?.name ||
    (s3Key ? s3Key.replace(/\\/g, "/").split("/").pop() : "") ||
    "sample.csv";

  const resolvedPath =
    path ||
    (s3Key
      ? s3Key.startsWith("s3://")
        ? s3Key
        : s3Key
      : undefined);

  if (persistRun) {
    let text = payloadText ?? "";
    if (file && !text) {
      text = await file.text();
    }
    let res: Response;
    try {
      res = await fetch(`${getEngineUrl()}/api/v1/airlock/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          property_id: propertyId,
          filename: resolvedName,
          path: resolvedPath,
          s3_uri: s3Key
            ? s3Key.startsWith("s3://")
              ? s3Key
              : resolvedPath || s3Key
            : undefined,
          payload_text: text,
          present_batch_filenames: presentBatchFilenames,
          contract_json: contract,
          fetch_uri: fetchUri && !file && Boolean(s3Key),
          persist_run: true,
          feed_category: feedCategory || undefined,
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
        `Evaluate failed (${res.status}): ${await parseError(res)}`
      );
    }
    return (await res.json()) as DryRunReport;
  }

  const useMultipart = Boolean(file) || Boolean(s3Key);

  if (useMultipart) {
    const form = new FormData();
    form.append("property_id", propertyId);
    form.append("filename", resolvedName);
    if (resolvedPath) form.append("path", resolvedPath);
    if (s3Key) {
      form.append(
        "s3_uri",
        s3Key.startsWith("s3://") ? s3Key : resolvedPath || s3Key
      );
    }
    if (presentBatchFilenames.length) {
      form.append("present_batch_filenames", presentBatchFilenames.join(","));
    }
    form.append("contract_json", JSON.stringify(contract));
    form.append("fetch_uri", fetchUri && !file ? "true" : "false");
    if (file) form.append("file", file, file.name);

    let res: Response;
    try {
      res = await fetch(`${getEngineUrl()}/api/v1/airlock/dry-run/upload`, {
        method: "POST",
        body: form,
      });
    } catch (e) {
      throw new Error(
        e instanceof Error
          ? `Engine unreachable: ${e.message}`
          : "Engine unreachable — is the FastAPI server running?"
      );
    }

    if (!res.ok) {
      throw new Error(`Dry-run failed (${res.status}): ${await parseError(res)}`);
    }
    return (await res.json()) as DryRunReport;
  }

  let res: Response;
  try {
    res = await fetch(`${getEngineUrl()}/api/v1/airlock/dry-run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        property_id: propertyId,
        filename: resolvedName,
        path: resolvedPath,
        payload_text: payloadText ?? "",
        present_batch_filenames: presentBatchFilenames,
        contract_json: contract,
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
    throw new Error(`Dry-run failed (${res.status}): ${await parseError(res)}`);
  }
  return (await res.json()) as DryRunReport;
}
