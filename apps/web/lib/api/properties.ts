import { supabase } from "@/lib/supabase";
import type {
  CreateFeedInput,
  CreatePropertyInput,
  Customer,
  CustomerTree,
  IngestionContract,
  Property,
  PropertyFeed,
  PropertyWithFeeds,
  SaveFeedContractInput,
} from "@/app/properties/setup/types";
import { defaultPrefix } from "@/app/properties/setup/presets";

export function isSupabaseConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  );
}

function slugCode(name: string): string {
  return name
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, 32);
}

function normalizeTime(t: string): string {
  if (!t) return "07:00:00";
  return t.length === 5 ? `${t}:00` : t;
}

/** Load customers → properties → feeds tree. */
export async function fetchCustomerTree(): Promise<CustomerTree[]> {
  if (!isSupabaseConfigured()) return [];

  const { data: customers, error: cErr } = await supabase
    .from("customers")
    .select("*")
    .order("customer_name");
  if (cErr) throw new Error(`Failed to load customers: ${cErr.message}`);

  const { data: properties, error: pErr } = await supabase
    .from("properties")
    .select("*")
    .order("property_name");
  if (pErr) throw new Error(`Failed to load properties: ${pErr.message}`);

  const { data: feeds, error: fErr } = await supabase
    .from("property_feeds")
    .select("*")
    .order("created_at");
  if (fErr) throw new Error(`Failed to load property_feeds: ${fErr.message}`);

  const feedByProp = new Map<string, PropertyFeed[]>();
  for (const f of (feeds ?? []) as PropertyFeed[]) {
    const key = f.property_id;
    const list = feedByProp.get(key) ?? [];
    list.push(f);
    feedByProp.set(key, list);
  }

  const propsByCustomer = new Map<string, PropertyWithFeeds[]>();
  const orphanProps: PropertyWithFeeds[] = [];

  for (const p of (properties ?? []) as Property[]) {
    const enriched: PropertyWithFeeds = {
      ...p,
      property_feeds: feedByProp.get(p.property_id) ?? [],
    };
    if (p.customer_id) {
      const list = propsByCustomer.get(p.customer_id) ?? [];
      list.push(enriched);
      propsByCustomer.set(p.customer_id, list);
    } else {
      orphanProps.push(enriched);
    }
  }

  const tree: CustomerTree[] = ((customers ?? []) as Customer[]).map((c) => ({
    ...c,
    properties: propsByCustomer.get(c.id) ?? [],
  }));

  if (orphanProps.length) {
    tree.push({
      id: "__unassigned__",
      customer_code: "UNASSIGNED",
      customer_name: "Unassigned",
      properties: orphanProps,
    });
  }

  return tree;
}

export async function fetchContract(
  contractId: string
): Promise<IngestionContract | null> {
  const { data, error } = await supabase
    .from("ingestion_contracts")
    .select("*")
    .eq("id", contractId)
    .maybeSingle();
  if (error) throw new Error(`Failed to load contract: ${error.message}`);
  return (data as IngestionContract) ?? null;
}

export async function createPropertyWithFirstFeed(
  input: CreatePropertyInput
): Promise<{ property: Property; feed: PropertyFeed; customer: Customer }> {
  if (!isSupabaseConfigured()) {
    throw new Error("Supabase is not configured.");
  }

  let customerId = input.customerId ?? null;
  let customer: Customer | null = null;

  if (customerId) {
    const { data, error } = await supabase
      .from("customers")
      .select("*")
      .eq("id", customerId)
      .maybeSingle();
    if (error) throw new Error(error.message);
    customer = data as Customer | null;
  }

  if (!customer) {
    const code = input.customerCode || slugCode(input.customerName);
    const { data, error } = await supabase
      .from("customers")
      .upsert(
        {
          customer_code: code,
          customer_name: input.customerName,
        },
        { onConflict: "customer_code" }
      )
      .select("*")
      .single();
    if (error) throw new Error(`Customer create failed: ${error.message}`);
    customer = data as Customer;
    customerId = customer.id;
  }

  const bucket = input.s3Bucket || "ing-airlock";
  const prefix =
    input.s3Prefix?.trim() ||
    defaultPrefix(input.propertyId, input.feedCategory);

  const { data: property, error: pErr } = await supabase
    .from("properties")
    .upsert(
      {
        property_id: input.propertyId.trim().toUpperCase(),
        property_name: input.propertyName.trim(),
        customer_id: customerId,
        timezone: input.timezone,
        sla_cutoff_time: normalizeTime(input.slaCutoff),
        sla_grace_period_mins: 60,
        s3_bucket: bucket,
        s3_prefix_pattern: prefix,
      },
      { onConflict: "property_id" }
    )
    .select("*")
    .single();
  if (pErr) throw new Error(`Property create failed: ${pErr.message}`);

  const { data: feed, error: fErr } = await supabase
    .from("property_feeds")
    .insert({
      property_id: (property as Property).property_id,
      feed_category: input.feedCategory,
      preset_id: input.presetId,
      schedule: input.schedule,
      sla_cutoff_time: normalizeTime(input.slaCutoff),
      s3_prefix: prefix,
    })
    .select("*")
    .single();
  if (fErr) throw new Error(`Feed create failed: ${fErr.message}`);

  return {
    property: property as Property,
    feed: feed as PropertyFeed,
    customer,
  };
}

export async function createFeed(
  input: CreateFeedInput
): Promise<PropertyFeed> {
  if (!isSupabaseConfigured()) {
    throw new Error("Supabase is not configured.");
  }
  const prefix =
    input.s3Prefix?.trim() ||
    defaultPrefix(input.propertyId, input.feedCategory);

  // Upsert on (property_id, feed_category) so preset switches never insert
  // a second POS/PMS row and trip uq_property_feed.
  const { data, error } = await supabase
    .from("property_feeds")
    .upsert(
      {
        property_id: input.propertyId,
        feed_category: input.feedCategory,
        preset_id: input.presetId,
        schedule: input.schedule,
        sla_cutoff_time: normalizeTime(input.slaCutoff),
        s3_prefix: prefix,
      },
      { onConflict: "property_id,feed_category" }
    )
    .select("*")
    .single();
  if (error) throw new Error(`Feed create failed: ${error.message}`);
  return data as PropertyFeed;
}

export async function updateFeed(
  feedId: string,
  patch: Partial<
    Pick<
      PropertyFeed,
      | "feed_category"
      | "preset_id"
      | "schedule"
      | "sla_cutoff_time"
      | "s3_prefix"
      | "active_contract_id"
    >
  >
): Promise<PropertyFeed> {
  const payload: Record<string, unknown> = { ...patch };
  if (typeof payload.sla_cutoff_time === "string") {
    payload.sla_cutoff_time = normalizeTime(String(payload.sla_cutoff_time));
  }
  const { data, error } = await supabase
    .from("property_feeds")
    .update(payload)
    .eq("id", feedId)
    .select("*")
    .single();
  if (error) throw new Error(`Feed update failed: ${error.message}`);
  return data as PropertyFeed;
}

export async function deleteFeed(feedId: string): Promise<void> {
  const { error } = await supabase
    .from("property_feeds")
    .delete()
    .eq("id", feedId);
  if (error) throw new Error(`Feed delete failed: ${error.message}`);
}

export async function updateProperty(
  propertyId: string,
  patch: Partial<
    Pick<
      Property,
      | "property_name"
      | "timezone"
      | "sla_cutoff_time"
      | "sla_grace_period_mins"
      | "alert_emails"
      | "slack_channel"
      | "s3_bucket"
      | "s3_prefix_pattern"
    >
  >
): Promise<Property> {
  const payload: Record<string, unknown> = { ...patch };
  if (typeof payload.sla_cutoff_time === "string") {
    payload.sla_cutoff_time = normalizeTime(String(payload.sla_cutoff_time));
  }
  const { data, error } = await supabase
    .from("properties")
    .update(payload)
    .eq("property_id", propertyId)
    .select("*")
    .single();
  if (error) throw new Error(`Property update failed: ${error.message}`);
  return data as Property;
}

/**
 * Persist contract JSON into ingestion_contracts and point
 * property_feeds.active_contract_id at the new/updated row.
 */
export async function saveFeedContract(
  input: SaveFeedContractInput
): Promise<{ contract: IngestionContract; feed: PropertyFeed }> {
  if (!isSupabaseConfigured()) {
    throw new Error("Supabase is not configured.");
  }

  let contract: IngestionContract;
  // Epoch-ms revision token — requires BIGINT on ingestion_contracts.version
  // (INT4 overflows for values like 1786501628757).
  const version = input.version ?? Date.now();

  if (input.existingContractId) {
    const { data, error } = await supabase
      .from("ingestion_contracts")
      .update({
        profile_id: input.profileId,
        file_format: input.fileFormat,
        contract_yaml: input.contractYaml,
        updated_at: new Date().toISOString(),
      })
      .eq("id", input.existingContractId)
      .select("*")
      .single();
    if (error) throw new Error(`Contract update failed: ${error.message}`);
    contract = data as IngestionContract;
  } else {
    const { data, error } = await supabase
      .from("ingestion_contracts")
      .insert({
        profile_id: input.profileId,
        version,
        file_format: input.fileFormat,
        contract_yaml: input.contractYaml,
      })
      .select("*")
      .single();
    if (error) throw new Error(`Contract insert failed: ${error.message}`);
    contract = data as IngestionContract;
  }

  const { data: feed, error: fErr } = await supabase
    .from("property_feeds")
    .update({ active_contract_id: contract.id })
    .eq("id", input.feedId)
    .select("*")
    .single();
  if (fErr) throw new Error(`Feed contract link failed: ${fErr.message}`);

  // Keep property-level pointer in sync for engine property lookups
  await supabase
    .from("properties")
    .update({ active_contract_id: contract.id })
    .eq("property_id", input.propertyId);

  return { contract, feed: feed as PropertyFeed };
}
