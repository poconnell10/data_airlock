/**
 * Airlock Contract v2 — GitOps-friendly YAML schema for Property Setup export.
 */
import type { FeedCategory, FeedContractForm } from "@/app/properties/setup/types";
import { toPythonNamedGroups } from "@/app/properties/setup/presets";

export const AIRLOCK_CONTRACT_VERSION = "2.0" as const;

export interface AirlockContractV2Metadata {
  property_id: string;
  feed_category: string;
  system_preset: string;
  updated_at: string;
}

export interface AirlockContractV2Gates {
  gate1_extraction: {
    filename_pattern: string;
    delimiter: string;
    encoding: string;
    atomic_set_members: string[];
    hold_set_enabled: boolean;
  };
  gate2_anomaly: {
    zscore_threshold: number;
    rolling_window_days: number;
  };
  gate3_quality: {
    required_columns: string[];
  };
  gate4_revenue: {
    tolerance_eur: number;
  };
}

export interface AirlockContractV2 {
  version: typeof AIRLOCK_CONTRACT_VERSION;
  metadata: AirlockContractV2Metadata;
  gates: AirlockContractV2Gates;
}

export interface ExportContractState {
  propertyId: string;
  feedCategory: FeedCategory | string;
  systemPreset: string;
  form: FeedContractForm;
  updatedAt?: string;
}

function splitCsv(raw: string): string[] {
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Infer required columns from header pattern chips when Gate 3 has no explicit list. */
function inferRequiredColumns(form: FeedContractForm): string[] {
  const header = form.headerPatterns
    .split("\n")
    .map((s) => s.trim())
    .find(Boolean);
  if (!header) return ["check_id", "business_date", "total_amount"];
  // e.g. "^check_id\\|" → check_id
  const bare = header.replace(/^\^/, "").replace(/\\\|.*/, "").replace(/\|.*/, "");
  if (bare && /^[A-Za-z_][A-Za-z0-9_]*$/.test(bare)) {
    return [bare, "business_date", "total_amount"];
  }
  return ["check_id", "business_date", "total_amount"];
}

/** Build the standardized AirlockContractV2 document from setup form state. */
export function buildAirlockContractV2(
  state: ExportContractState
): AirlockContractV2 {
  const members = splitCsv(state.form.atomicMembers);
  return {
    version: AIRLOCK_CONTRACT_VERSION,
    metadata: {
      property_id: state.propertyId,
      feed_category: String(state.feedCategory).toUpperCase(),
      system_preset: state.systemPreset,
      updated_at: state.updatedAt ?? new Date().toISOString(),
    },
    gates: {
      gate1_extraction: {
        filename_pattern: toPythonNamedGroups(state.form.filenameRegex),
        delimiter: state.form.delimiter,
        encoding: state.form.encoding.toLowerCase().replace("utf-8-bom", "utf-8"),
        atomic_set_members: members,
        hold_set_enabled: state.form.isAtomic,
      },
      gate2_anomaly: {
        zscore_threshold: state.form.maxZScore,
        rolling_window_days: state.form.frozenWindow ? 30 : 3650,
      },
      gate3_quality: {
        required_columns: inferRequiredColumns(state.form),
      },
      gate4_revenue: {
        tolerance_eur: state.form.maxVariance,
      },
    },
  };
}

function yamlScalar(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "null";
  if (typeof value === "string") {
    // Quote when YAML-special / ambiguous (e.g. version "2.0")
    if (
      value === "" ||
      /[:#{}[\],&*?|<>=!%@`\\]/.test(value) ||
      /^(true|false|null|yes|no)$/i.test(value) ||
      /^-?\d+(\.\d+)?$/.test(value) ||
      /^\s|\s$/.test(value)
    ) {
      return JSON.stringify(value);
    }
    return value;
  }
  return JSON.stringify(value);
}

function dumpYaml(value: unknown, indent = 0): string {
  const pad = "  ".repeat(indent);
  if (Array.isArray(value)) {
    if (value.length === 0) return `${pad}[]`;
    return value
      .map((item) => {
        if (item !== null && typeof item === "object" && !Array.isArray(item)) {
          const nested = dumpYaml(item, indent + 1);
          const lines = nested.split("\n");
          const first = lines[0]?.replace(/^\s+/, "") ?? "";
          const rest = lines.slice(1).join("\n");
          return rest
            ? `${pad}- ${first}\n${rest}`
            : `${pad}- ${first}`;
        }
        return `${pad}- ${yamlScalar(item)}`;
      })
      .join("\n");
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return `${pad}{}`;
    return entries
      .map(([key, child]) => {
        if (child !== null && typeof child === "object") {
          const nested = dumpYaml(child, indent + 1);
          if (Array.isArray(child) && child.length === 0) {
            return `${pad}${key}: []`;
          }
          return `${pad}${key}:\n${nested}`;
        }
        return `${pad}${key}: ${yamlScalar(child)}`;
      })
      .join("\n");
  }
  return `${pad}${yamlScalar(value)}`;
}

export function contractFilename(
  propertyId: string,
  systemPreset: string,
  feedCategory?: string
): string {
  const cat = (feedCategory || "").toLowerCase();
  const preset = systemPreset.toLowerCase().replace(/[^a-z0-9_]+/g, "_");
  const suffix = cat && !preset.endsWith(`_${cat}`) ? `${preset}_${cat}` : preset;
  return `contract_${propertyId}_${suffix}.yaml`;
}

/**
 * Serialize setup state to AirlockContractV2 YAML and trigger a browser download.
 * Returns the generated filename.
 */
export function exportContractToYaml(state: ExportContractState): {
  filename: string;
  yaml: string;
  contract: AirlockContractV2;
} {
  const contract = buildAirlockContractV2(state);
  const yaml = `${dumpYaml(contract)}\n`;
  const filename = contractFilename(
    state.propertyId,
    state.systemPreset,
    String(state.feedCategory)
  );

  if (typeof document !== "undefined") {
    const blob = new Blob([yaml], { type: "application/x-yaml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return { filename, yaml, contract };
}
