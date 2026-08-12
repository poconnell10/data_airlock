import { supabase } from "@/lib/supabase";
import type {
  AlertRules,
  IngestionContractRow,
  PropertyRow,
} from "@/lib/types";

export function isSupabaseConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  );
}

export async function fetchPropertyBundle(propertyId: string): Promise<{
  property: PropertyRow | null;
  contract: IngestionContractRow | null;
}> {
  if (!isSupabaseConfigured()) {
    return { property: null, contract: null };
  }

  const { data: property, error: propErr } = await supabase
    .from("properties")
    .select("*")
    .eq("property_id", propertyId)
    .maybeSingle();

  if (propErr) {
    throw new Error(`Failed to load property: ${propErr.message}`);
  }

  if (!property) {
    return { property: null, contract: null };
  }

  let contract: IngestionContractRow | null = null;
  if (property.active_contract_id) {
    const { data: contractRow, error: cErr } = await supabase
      .from("ingestion_contracts")
      .select("*")
      .eq("id", property.active_contract_id)
      .maybeSingle();
    if (cErr) {
      throw new Error(`Failed to load contract: ${cErr.message}`);
    }
    contract = (contractRow as IngestionContractRow) ?? null;
  }

  return {
    property: property as PropertyRow,
    contract,
  };
}

export interface SaveContractInput {
  propertyId: string;
  propertyName: string;
  vendorTemplate: string;
  timezone: string;
  slaCutoff: string;
  s3Bucket: string;
  s3Prefix: string;
  gracePeriodMinutes: number;
  alertRules: AlertRules;
  profileId: string;
  version: string;
  fileFormat: string;
  contractYaml: Record<string, unknown>;
  description?: string;
  existingContractId?: string | null;
  existingPropertyUuid?: string | null;
}

export async function saveAirlockContract(input: SaveContractInput): Promise<{
  property: PropertyRow;
  contract: IngestionContractRow;
}> {
  if (!isSupabaseConfigured()) {
    throw new Error(
      "Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY."
    );
  }

  // Normalize HH:MM → HH:MM:SS for Postgres time
  const sla =
    input.slaCutoff.length === 5 ? `${input.slaCutoff}:00` : input.slaCutoff;

  let contract: IngestionContractRow;

  if (input.existingContractId) {
    const { data, error } = await supabase
      .from("ingestion_contracts")
      .update({
        profile_id: input.profileId,
        version: input.version,
        file_format: input.fileFormat,
        contract_yaml: input.contractYaml,
        description: input.description ?? null,
      })
      .eq("id", input.existingContractId)
      .select("*")
      .single();
    if (error) throw new Error(`Contract update failed: ${error.message}`);
    contract = data as IngestionContractRow;
  } else {
    const { data, error } = await supabase
      .from("ingestion_contracts")
      .upsert(
        {
          profile_id: input.profileId,
          version: input.version,
          file_format: input.fileFormat,
          contract_yaml: input.contractYaml,
          description: input.description ?? null,
        },
        { onConflict: "profile_id,version" }
      )
      .select("*")
      .single();
    if (error) throw new Error(`Contract upsert failed: ${error.message}`);
    contract = data as IngestionContractRow;
  }

  const propertyPayload = {
    property_id: input.propertyId,
    name: input.propertyName,
    active: true,
    vendor_template: input.vendorTemplate,
    active_contract_id: contract.id,
    s3_bucket: input.s3Bucket,
    s3_prefix: input.s3Prefix,
    local_timezone: input.timezone,
    sla_delivery_cutoff: sla,
    grace_period_minutes: input.gracePeriodMinutes,
    alert_rules: input.alertRules,
  };

  const { data: property, error: propErr } = await supabase
    .from("properties")
    .upsert(propertyPayload, { onConflict: "property_id" })
    .select("*")
    .single();

  if (propErr) {
    throw new Error(`Property upsert failed: ${propErr.message}`);
  }

  return {
    property: property as PropertyRow,
    contract,
  };
}
