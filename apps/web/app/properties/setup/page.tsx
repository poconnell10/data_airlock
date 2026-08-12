"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { saveAirlockContract } from "@/lib/api/contracts";
import {
  createFeed,
  createPropertyWithFirstFeed,
  fetchContract,
  fetchCustomerTree,
  isSupabaseConfigured,
  updateFeed,
} from "@/lib/api/properties";
import {
  buildAirlockContractV2,
  exportContractToYaml,
} from "@/lib/contracts/schema";
import { AddFeedDrawer } from "./components/AddFeedDrawer";
import { AddPropertyDrawer } from "./components/AddPropertyDrawer";
import { ContractWorkbench } from "./components/ContractWorkbench";
import { FeedTabBar } from "./components/FeedTabBar";
import { PresetTierBar } from "./components/PresetTierBar";
import {
  PropertyHeader,
  PropertyTopBar,
} from "./components/PropertyHeader";
import { TestBenchDrawer } from "./components/TestBenchDrawer";
import { Toast } from "./components/Toast";
import {
  buildFeedContractYaml,
  formFromPreset,
  isFileCategory,
  presetsForCategory,
  toJsNamedGroups,
} from "./presets";
import type {
  CustomerTree,
  FeedCategory,
  FeedContractForm,
  PropertyFeed,
  PropertyWithFeeds,
} from "./types";

function cutTime(raw: string | null | undefined, fallback = "07:00"): string {
  if (!raw) return fallback;
  return raw.slice(0, 5);
}

export default function PropertySetupPage() {
  const [tree, setTree] = useState<CustomerTree[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [propertyId, setPropertyId] = useState<string | null>(null);
  const [feedId, setFeedId] = useState<string | null>(null);
  const [form, setForm] = useState<FeedContractForm>(() =>
    formFromPreset("onesait")
  );
  const [section, setSection] = useState(1);
  const [contractStatus, setContractStatus] = useState<"draft" | "published">(
    "draft"
  );

  const [toast, setToast] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [addPropOpen, setAddPropOpen] = useState(false);
  const [addFeedOpen, setAddFeedOpen] = useState(false);
  const [benchOpen, setBenchOpen] = useState(false);

  const property: PropertyWithFeeds | null = useMemo(() => {
    for (const c of tree) {
      const hit = c.properties.find((p) => p.property_id === propertyId);
      if (hit) return { ...hit, customer: c };
    }
    return null;
  }, [tree, propertyId]);

  const customerName =
    property?.customer?.customer_name ||
    tree.find((c) => c.properties.some((p) => p.property_id === propertyId))
      ?.customer_name ||
    "—";

  const feed: PropertyFeed | null =
    property?.property_feeds.find((f) => f.id === feedId) ??
    property?.property_feeds[0] ??
    null;

  const reload = useCallback(async (preferPropertyId?: string, preferFeedId?: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      if (!isSupabaseConfigured()) {
        setLoadError(
          "Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY."
        );
        setTree([]);
        return;
      }
      const data = await fetchCustomerTree();
      setTree(data);
      const flat = data.flatMap((c) => c.properties);
      const nextProp =
        flat.find((p) => p.property_id === preferPropertyId) ||
        flat.find((p) => p.property_id === propertyId) ||
        flat[0] ||
        null;
      setPropertyId(nextProp?.property_id ?? null);
      const nextFeed =
        nextProp?.property_feeds.find((f) => f.id === preferFeedId) ||
        nextProp?.property_feeds.find((f) => f.id === feedId) ||
        nextProp?.property_feeds[0] ||
        null;
      setFeedId(nextFeed?.id ?? null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load properties");
    } finally {
      setLoading(false);
    }
  }, [feedId, propertyId]);

  useEffect(() => {
    void reload();
    // initial load only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Hydrate form when feed changes
  useEffect(() => {
    if (!feed || !property) return;
    let cancelled = false;
    (async () => {
      let next = formFromPreset(feed.preset_id, {
        timezone: property.timezone || "UTC",
        cutoff: cutTime(feed.sla_cutoff_time),
        graceMinutes: property.sla_grace_period_mins ?? 60,
        alertEmails: (property.alert_emails || []).join(", "),
        slackChannel: property.slack_channel || "#data-ops-alerts",
        manifestPrefix: `s3://ing-airlock/reports/${property.property_id}/`,
      });
      if (feed.active_contract_id) {
        try {
          const contract = await fetchContract(feed.active_contract_id);
          if (contract && !cancelled) {
            setContractStatus("published");
            const yaml = contract.contract_yaml || {};
            const ff =
              (yaml.file_format as Record<string, unknown>) || {};
            const fn = (yaml.filename as Record<string, unknown>) || {};
            const rc =
              (yaml.row_classification as Record<string, unknown>) || {};
            const atomic = (yaml.atomic_set as Record<string, unknown>) || {};
            const obj =
              (yaml.object_landing as Record<string, unknown>) || {};
            const g2 = (yaml.gate_2 as Record<string, unknown>) || {};
            const g4 = (yaml.gate_4 as Record<string, unknown>) || {};
            const sched = (yaml.schedule as Record<string, unknown>) || {};
            next = {
              ...next,
              timezone: String(sched.timezone || next.timezone),
              cutoff: cutTime(String(sched.sla_cutoff_time || next.cutoff)),
              graceMinutes: Number(
                sched.grace_period_minutes ?? next.graceMinutes
              ),
              encoding: String(ff.encoding || next.encoding).toUpperCase(),
              delimiter: String(ff.delimiter || next.delimiter),
              filenameRegex: toJsNamedGroups(
                String(fn.pattern || next.filenameRegex)
              ),
              headerPatterns: Array.isArray(rc.header_patterns)
                ? rc.header_patterns.join("\n")
                : next.headerPatterns,
              footerPatterns: Array.isArray(rc.footer_patterns)
                ? rc.footer_patterns.join("\n")
                : next.footerPatterns,
              isAtomic: Boolean(atomic.is_multi_file),
              atomicMembers: Array.isArray(atomic.required_endpoints)
                ? atomic.required_endpoints.join(", ")
                : next.atomicMembers,
              objectFormat: String(obj.format || next.objectFormat),
              partitionKey: String(obj.partition_key || next.partitionKey),
              watermarkColumn: String(
                obj.watermark_column || next.watermarkColumn
              ),
              partitionPath: String(obj.partition_path || next.partitionPath),
              requireCommitMarker: Boolean(
                obj.require_commit_marker ?? next.requireCommitMarker
              ),
              maxZScore: Number(g2.max_z_score ?? next.maxZScore),
              headerVsLine: Boolean(
                g4.header_vs_line_balance ?? next.headerVsLine
              ),
              salesVsTender: Boolean(
                g4.sales_vs_tender_balance ?? next.salesVsTender
              ),
              maxVariance: Number(g4.max_variance ?? next.maxVariance),
            };
          }
        } catch {
          /* keep preset defaults */
        }
      } else {
        setContractStatus("draft");
      }
      if (!cancelled) setForm(next);
    })();
    return () => {
      cancelled = true;
    };
  }, [feed?.id, property?.property_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const onCategory = async (cat: FeedCategory) => {
    if (!feed) return;
    const first = presetsForCategory(cat)[0];
    if (!first) return;
    setForm(formFromPreset(first.id, { ...form, cutoff: form.cutoff }));
    try {
      await updateFeed(feed.id, {
        feed_category: cat,
        preset_id: first.id,
        s3_prefix: `s3://ing-airlock/raw/${propertyId}/${cat}/`,
      });
      setToast(`${cat.toUpperCase()} selected — contract rules updated`);
      await reload(propertyId ?? undefined, feed.id);
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Failed to update feed");
    }
  };

  const onPreset = async (preset: string) => {
    if (!feed || !property) return;
    setForm(formFromPreset(preset, { ...form, cutoff: form.cutoff }));
    try {
      // Update the existing category feed in-place (never insert a sibling POS row).
      await updateFeed(feed.id, { preset_id: preset });
      setToast("Preset applied — review before saving");
      await reload(property.property_id, feed.id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to update preset";
      setToast(
        msg.includes("uq_property_feed")
          ? "Could not switch preset: a conflicting feed row exists for this category. Refresh and retry."
          : msg
      );
    }
  };

  const onExportYaml = () => {
    if (!feed || !property) return;
    exportContractToYaml({
      propertyId: property.property_id,
      feedCategory: feed.feed_category,
      systemPreset: feed.preset_id,
      form,
    });
    setToast(`Exported contract YAML for ${property.property_id}`);
  };

  const onSave = async () => {
    if (!feed || !property) return;
    setSaving(true);
    try {
      const engineContract = buildFeedContractYaml(form, {
        propertyId: property.property_id,
        feedCategory: feed.feed_category,
        presetId: feed.preset_id,
        s3Prefix: feed.s3_prefix,
      });
      const contractV2 = buildAirlockContractV2({
        propertyId: property.property_id,
        feedCategory: feed.feed_category,
        systemPreset: feed.preset_id,
        form,
      });
      const fileFormat = isFileCategory(feed.feed_category)
        ? "delimited_text"
        : String(form.objectFormat || "parquet").toLowerCase();

      await saveAirlockContract({
        propertyId: property.property_id,
        feedId: feed.id,
        feedCategory: feed.feed_category,
        systemPreset: feed.preset_id,
        fileFormat,
        contractV2,
        engineContract,
        timezone: form.timezone,
        slaCutoff: form.cutoff,
        graceMinutes: form.graceMinutes,
        alertEmails: form.alertEmails
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        slackChannel: form.slackChannel,
        existingContractId: feed.active_contract_id,
        form,
      });
      setContractStatus("published");
      setToast("Airlock contract successfully published to database.");
      await reload(property.property_id, feed.id);
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="setup-root">
      {loading ? (
        <div className="setup-skel">
          <div className="skel h-12" />
          <div className="skel h-28 mt-4" />
          <div className="skel h-14 mt-4" />
          <div className="grid grid-cols-[246px_1fr] gap-5 mt-6">
            <div className="skel h-80" />
            <div className="skel h-80" />
          </div>
        </div>
      ) : (
        <div className="setup-main">
          <PropertyTopBar
            tree={tree}
            property={property}
            contractLabel={`contract · ${contractStatus}`}
            onSelectProperty={(id) => {
              setPropertyId(id);
              setContractStatus("draft");
              const p = tree
                .flatMap((c) => c.properties)
                .find((x) => x.property_id === id);
              setFeedId(p?.property_feeds[0]?.id ?? null);
            }}
            onAddProperty={() => setAddPropOpen(true)}
            onOpenTestBench={() => setBenchOpen(true)}
          />

          <div className="setup-scroll">
            <div className="setup-wrap">
              {loadError && (
                <div className="banner-err" role="alert">
                  {loadError}
                </div>
              )}

              <PropertyHeader
                property={property}
                feed={feed}
                customerName={customerName}
                onOpenTestBench={() => setBenchOpen(true)}
                onSave={() => void onSave()}
                onExportYaml={onExportYaml}
                saving={saving}
              />

              {property && feed ? (
                <>
                  <FeedTabBar
                    feeds={property.property_feeds}
                    activeFeedId={feed.id}
                    onSelect={setFeedId}
                    onAddFeed={() => setAddFeedOpen(true)}
                  />
                  <PresetTierBar
                    category={feed.feed_category}
                    presetId={feed.preset_id}
                    onCategory={(c) => void onCategory(c)}
                    onPreset={(p) => void onPreset(p)}
                  />
                  <ContractWorkbench
                    category={feed.feed_category}
                    form={form}
                    section={section}
                    onSection={setSection}
                    onChange={(patch) => {
                      setForm((f) => ({ ...f, ...patch }));
                      if (contractStatus === "published") {
                        setContractStatus("draft");
                      }
                    }}
                  />
                </>
              ) : (
                <div className="empty-state">
                  <h2>No properties yet</h2>
                  <p>Onboard a customer property to configure its first feed.</p>
                  <button
                    type="button"
                    className="btn pri"
                    onClick={() => setAddPropOpen(true)}
                  >
                    Add property
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <AddPropertyDrawer
        open={addPropOpen}
        customers={tree}
        onClose={() => setAddPropOpen(false)}
        onSubmit={async (input) => {
          const res = await createPropertyWithFirstFeed(input);
          setToast(`Created ${res.property.property_name}`);
          await reload(res.property.property_id, res.feed.id);
        }}
      />
      {property && (
        <AddFeedDrawer
          open={addFeedOpen}
          propertyId={property.property_id}
          existingFeeds={property.property_feeds}
          onClose={() => setAddFeedOpen(false)}
          onSubmit={async (input) => {
            const f = await createFeed(input);
            setToast("Feed created — configure its contract");
            await reload(property.property_id, f.id);
          }}
        />
      )}
      <TestBenchDrawer
        open={benchOpen}
        property={property}
        feed={feed}
        form={form}
        onClose={() => setBenchOpen(false)}
        onToast={setToast}
      />
      <Toast message={toast} onDone={() => setToast(null)} />
    </div>
  );
}
