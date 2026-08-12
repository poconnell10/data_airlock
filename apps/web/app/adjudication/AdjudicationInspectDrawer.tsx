"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";
import {
  buildManifestFromGateEvaluations,
  classifyRun,
  extractFailureHighlights,
  releaseRun,
  type AdjudicationItem,
} from "@/lib/adjudication";
import { postRunAuditNote } from "@/lib/api/journal";
import {
  QUARANTINE_CATEGORIES,
  emptyReadinessStats,
  formatRowCount,
  type QuarantineCategory,
  type QuarantineManifestItem,
  type ReadinessStats,
} from "@/lib/types/airlock";
import {
  QuarantineDecisionCard,
  type DecisionAction,
} from "./QuarantineDecisionCard";
import "../properties/setup/setup.css";

function outcomeBadge(outcome: string): string {
  switch (outcome) {
    case "QUARANTINE_FILE":
    case "REJECT_FILE":
      return "bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/40";
    case "HOLD_SET":
      return "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/40";
    case "RELEASED_TO_ETL":
    case "PASS_OVERRIDDEN":
      return "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/40";
    default:
      return "bg-slate-500/15 text-slate-300 ring-1 ring-slate-500/40";
  }
}

function resolveStats(item: AdjudicationItem): ReadinessStats {
  if (item.readiness_stats) return item.readiness_stats;
  const gates = item.gate_evaluations || {};
  const nested = gates.readiness_stats;
  if (nested && typeof nested === "object") {
    return nested as ReadinessStats;
  }
  return emptyReadinessStats();
}

function resolveManifest(item: AdjudicationItem): QuarantineManifestItem[] {
  if (Array.isArray(item.quarantine_manifest) && item.quarantine_manifest.length) {
    return item.quarantine_manifest;
  }
  const nested = item.gate_evaluations?.quarantine_manifest;
  if (Array.isArray(nested) && nested.length) {
    return nested as QuarantineManifestItem[];
  }
  // Rebuild from gate evaluations so Gate 4 failures still drive decision cards
  return buildManifestFromGateEvaluations(item.gate_evaluations || {});
}

const AUDIT_PRESETS = [
  "Verified with Night Auditor",
  "Vendor Balance Ticket",
  "Declared Short $7.50",
  "Need Weekly Sync",
] as const;

export function AdjudicationInspectDrawer({
  item,
  operatorId = "op_402",
  onClose,
  onDeclareShort,
  onItemPatch,
  onToast,
}: {
  item: AdjudicationItem;
  operatorId?: string;
  onClose: () => void;
  onDeclareShort: (item: AdjudicationItem) => void;
  onItemPatch?: (next: AdjudicationItem) => void;
  onToast?: (message: string) => void;
}) {
  const stats = resolveStats(item);
  const initialManifest = resolveManifest(item);
  const [manifest, setManifest] = useState(initialManifest);
  const [saving, setSaving] = useState(false);
  const [auditNotes, setAuditNotes] = useState<
    Array<{ at: string; text: string }>
  >([]);
  const [noteDraft, setNoteDraft] = useState("");
  const [noteSaving, setNoteSaving] = useState(false);

  useEffect(() => {
    setManifest(resolveManifest(item));
    setAuditNotes([]);
    setNoteDraft("");
  }, [item]);

  const persistAuditNote = async (
    text: string,
    noteType:
      | "DECISION_REASON"
      | "VENDOR_ESCALATION"
      | "MEETING_REQUIRED"
      | "THRESHOLD_ADJUSTMENT"
      | "NOTE_ADDED" = "DECISION_REASON"
  ) => {
    setAuditNotes((prev) => [
      { at: new Date().toISOString(), text },
      ...prev,
    ]);
    try {
      await postRunAuditNote(item.run_id, {
        operator_id: operatorId,
        content: text,
        note_type: noteType,
      });
    } catch (err) {
      onToast?.(
        err instanceof Error
          ? err.message
          : "Audit note saved locally; journal sync failed."
      );
    }
  };

  const highlights = useMemo(
    () => extractFailureHighlights(item.gate_evaluations || {}),
    [item]
  );

  const readyFromStats = Number(stats.readiness_pct ?? 100);
  const fileRejected =
    item.overall_outcome === "REJECT_FILE" ||
    readyFromStats === 0 ||
    stats.total_rows === 0;
  const readyPct = fileRejected ? 0 : readyFromStats;
  const quarPct = fileRejected
    ? 100
    : Number(stats.quarantine_pct ?? Math.max(0, 100 - readyPct));
  const readinessLabel = fileRejected
    ? `0 / ${formatRowCount(stats.total_rows)} rows ready (0.0% - File Rejected)`
    : `${formatRowCount(stats.verified_rows)} / ${formatRowCount(
        stats.total_rows
      )} rows ready (${readyPct.toFixed(1)}%)`;
  const readinessColor = fileRejected ? "text-rose-300" : "text-emerald-300";
  const readyBarClass = fileRejected ? "bg-rose-600" : "bg-emerald-500";
  const quarBarClass = fileRejected ? "bg-rose-500/90" : "bg-amber-500/90";

  const persistClassifications = async (
    next: QuarantineManifestItem[],
    patches: Array<{
      rule_id: string;
      user_category: QuarantineCategory;
      user_notes?: string | null;
    }>
  ) => {
    if (!patches.length) return next;
    setSaving(true);
    try {
      const res = await classifyRun(item.run_id, operatorId, patches);
      const saved = res.quarantine_manifest?.length
        ? res.quarantine_manifest
        : next;
      setManifest(saved);
      onItemPatch?.({ ...item, quarantine_manifest: saved });
      onToast?.(res.message || "Classifications saved.");
      return saved;
    } catch (err) {
      onToast?.(
        err instanceof Error ? err.message : "Failed to save classifications."
      );
      return next;
    } finally {
      setSaving(false);
    }
  };

  const onCategoryChange = async (
    ruleId: string,
    category: QuarantineCategory
  ) => {
    const next = manifest.map((row) =>
      row.rule_id === ruleId ? { ...row, user_category: category } : row
    );
    setManifest(next);
    await persistClassifications(next, [
      {
        rule_id: ruleId,
        user_category: category,
        user_notes: next.find((r) => r.rule_id === ruleId)?.user_notes ?? null,
      },
    ]);
  };

  const onSaveClassifications = async () => {
    const patches = manifest
      .filter((m) => m.user_category)
      .map((m) => ({
        rule_id: m.rule_id,
        user_category: m.user_category as QuarantineCategory,
        user_notes: m.user_notes ?? null,
      }));
    if (!patches.length) {
      onToast?.("Select at least one category override before saving.");
      return;
    }
    await persistClassifications(manifest, patches);
  };

  const onDecisionAction = async (
    action: DecisionAction,
    row: QuarantineManifestItem
  ) => {
    if (action === "copy_vendor_bundle") {
      const bundle = {
        property_id: item.property_id,
        business_date: item.business_date,
        report_type: item.report_type,
        run_id: item.run_id,
        rule_id: row.rule_id,
        message: row.message,
        decision_guidance: row.decision_guidance,
        sample_records: row.sample_records,
        outcome: item.overall_outcome,
      };
      try {
        await navigator.clipboard.writeText(JSON.stringify(bundle, null, 2));
        onToast?.("Vendor ticket diagnostic bundle copied to clipboard.");
      } catch {
        onToast?.("Unable to copy diagnostic bundle.");
      }
      return;
    }

    const notesByAction: Partial<Record<DecisionAction, string>> = {
      confirm_rejection: "Operator confirmed file rejection.",
      approve_release: "One-time override approve & release.",
      approve_autotune: "Approve and auto-tune contract threshold.",
      overwrite_baseline: "Overwrite certified historical baseline.",
      keep_original: "Keep original certified date; discard landing.",
      approve_exception: "Approved business-edge-case exception.",
      escalate_controller: "Escalated to property controller.",
      declare_short_release: "Declared short balancing entry and release.",
      reject_escalate_audit: "Rejected file and escalated to audit.",
      flag_for_sync: "Flagged for weekly sync / controller review.",
    };

    const categoryByAction: Partial<
      Record<DecisionAction, QuarantineCategory>
    > = {
      confirm_rejection: "DATA_QUALITY_BUG",
      approve_release: "FALSE_POSITIVE",
      approve_autotune: "FALSE_POSITIVE",
      overwrite_baseline: "OVERLAP_DRIFT",
      keep_original: "OVERLAP_DRIFT",
      approve_exception: "BUSINESS_EDGE_CASE",
      escalate_controller: "BUSINESS_EDGE_CASE",
      declare_short_release: "UNBALANCED_REVENUE",
      reject_escalate_audit: "UNBALANCED_REVENUE",
      flag_for_sync: "BUSINESS_EDGE_CASE",
    };

    const category = categoryByAction[action] || row.suggested_category;
    const notes = notesByAction[action] || action;
    const next = manifest.map((m) =>
      m.rule_id === row.rule_id
        ? { ...m, user_category: category, user_notes: notes }
        : m
    );
    setManifest(next);
    await persistClassifications(next, [
      { rule_id: row.rule_id, user_category: category, user_notes: notes },
    ]);
    const noteType =
      action === "reject_escalate_audit"
        ? ("VENDOR_ESCALATION" as const)
        : ("DECISION_REASON" as const);
    await persistAuditNote(notes, noteType);

    if (action === "declare_short_release") {
      onDeclareShort(item);
      return;
    }

    if (
      action === "approve_release" ||
      action === "approve_exception" ||
      action === "approve_autotune"
    ) {
      try {
        await releaseRun(item.run_id, {
          operator_id: operatorId,
          reason: notes,
        });
        onItemPatch?.({
          ...item,
          overall_outcome: "RELEASED_TO_ETL",
          quarantine_manifest: next,
        });
        onToast?.("Run released to ETL.");
      } catch (err) {
        onToast?.(
          err instanceof Error ? err.message : "Release failed after classify."
        );
      }
    }
  };

  const releasable =
    item.overall_outcome === "HOLD_SET" ||
    item.overall_outcome === "QUARANTINE_FILE";

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50 backdrop-blur-sm">
      <button
        type="button"
        className="absolute inset-0 cursor-default"
        aria-label="Close drawer"
        onClick={onClose}
      />
      <aside className="relative z-10 flex h-full w-full max-w-2xl flex-col border-l border-slate-800 bg-[#0d1526] shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-800 px-5 py-4">
          <div>
            <p className="font-mono text-xs text-cyan-300">{item.property_id}</p>
            <h3 className="mt-1 text-lg font-semibold text-white">
              Inspection · {item.report_type}
            </h3>
            <p className="mt-1 text-xs text-slate-500">{item.run_id}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
          <div className="flex flex-wrap gap-2">
            <span
              className={`inline-flex rounded-md px-2 py-1 font-mono text-[11px] ${outcomeBadge(
                item.overall_outcome
              )}`}
            >
              {item.overall_outcome}
            </span>
            <span className="rounded-md bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-300">
              {item.business_date}
            </span>
          </div>

          <section
            className="rounded-xl border border-slate-800 bg-slate-950/60 p-4"
            data-testid="readiness-panel"
          >
            <div className="mb-2 flex items-end justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Processing readiness
                </p>
                <p
                  className={`mt-1 font-mono text-2xl font-semibold ${readinessColor}`}
                  data-testid="readiness-pct"
                >
                  {readyPct.toFixed(1)}%
                </p>
              </div>
              <p
                className="rounded-md bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-slate-300"
                data-testid="readiness-pill"
              >
                {readinessLabel}
              </p>
            </div>
            <div
              className="flex h-3 overflow-hidden rounded-full bg-slate-800"
              role="progressbar"
              aria-valuenow={readyPct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Processing readiness"
            >
              {fileRejected ? (
                <div
                  className="h-full w-full bg-rose-600 transition-all"
                  data-testid="readiness-bar-quarantine"
                />
              ) : (
                <>
                  <div
                    className={`h-full transition-all ${readyBarClass}`}
                    style={{
                      width: `${Math.min(100, Math.max(0, readyPct))}%`,
                    }}
                    data-testid="readiness-bar-ready"
                  />
                  <div
                    className={`h-full transition-all ${quarBarClass}`}
                    style={{
                      width: `${Math.min(100, Math.max(0, quarPct))}%`,
                    }}
                    data-testid="readiness-bar-quarantine"
                  />
                </>
              )}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              {fileRejected
                ? "0.0% Ready · 100.0% Quarantined"
                : `Quarantine ${quarPct.toFixed(1)}% · ${formatRowCount(
                    stats.quarantined_rows
                  )} rows held`}
            </p>
          </section>

          {manifest.length > 0 && (
            <section
              className="space-y-3"
              data-testid="decision-guidance-panel"
            >
              <h4 className="text-sm font-semibold text-slate-200">
                Decision guidance
              </h4>
              {manifest.map((row) => (
                <QuarantineDecisionCard
                  key={`decision-${row.rule_id}`}
                  item={row}
                  run={item}
                  onAction={(action, r) => void onDecisionAction(action, r)}
                />
              ))}
            </section>
          )}

          <section
            className="rounded-xl border border-slate-800 bg-slate-950/60 p-4"
            data-testid="audit-notes-panel"
          >
            <h4 className="text-sm font-semibold text-slate-200">
              Decision &amp; Audit Notes
            </h4>
            <div className="mt-2 flex flex-wrap gap-2">
              {AUDIT_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  className="rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 text-[11px] text-slate-300 hover:border-cyan-700 hover:text-cyan-200"
                  onClick={() => {
                    void (async () => {
                      const text = `+ ${preset}`;
                      const noteType =
                        preset === "Vendor Balance Ticket"
                          ? ("VENDOR_ESCALATION" as const)
                          : ("DECISION_REASON" as const);
                      await persistAuditNote(text, noteType);
                      onToast?.(`Audit note added: ${preset}`);
                    })();
                  }}
                >
                  + {preset}
                </button>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <input
                value={noteDraft}
                onChange={(e) => setNoteDraft(e.target.value)}
                placeholder="Add freeform operator note…"
                className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-cyan-600"
              />
              <button
                type="button"
                className="btn sec sm"
                disabled={!noteDraft.trim() || noteSaving}
                onClick={() => {
                  void (async () => {
                    const text = noteDraft.trim();
                    if (!text) return;
                    setNoteSaving(true);
                    try {
                      await persistAuditNote(text, "DECISION_REASON");
                      setNoteDraft("");
                    } finally {
                      setNoteSaving(false);
                    }
                  })();
                }}
              >
                {noteSaving ? "Saving…" : "Add"}
              </button>
            </div>
            <ul className="mt-3 max-h-40 space-y-2 overflow-y-auto">
              {auditNotes.length === 0 ? (
                <li className="text-xs text-slate-500">No audit notes yet.</li>
              ) : (
                auditNotes.map((n) => (
                  <li
                    key={`${n.at}-${n.text}`}
                    className="rounded-md border border-slate-800 bg-slate-950/80 px-2.5 py-2 text-xs text-slate-300"
                  >
                    <span className="font-mono text-[10px] text-slate-500">
                      {new Date(n.at).toLocaleString()}
                    </span>
                    <div className="mt-0.5">{n.text}</div>
                  </li>
                ))
              )}
            </ul>
          </section>

          <section data-testid="quarantine-manifest">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-sm font-semibold text-slate-200">
                Quarantine manifest
              </h4>
              <button
                type="button"
                className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-900 disabled:opacity-50"
                disabled={saving || !manifest.length}
                onClick={() => void onSaveClassifications()}
              >
                {saving ? (
                  <span className="inline-flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" /> Saving…
                  </span>
                ) : (
                  "Save classifications"
                )}
              </button>
            </div>
            {manifest.length === 0 ? (
              <p className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-6 text-center text-sm text-slate-500">
                No quarantine diagnostics for this run.
              </p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-slate-800">
                <table className="min-w-full text-left text-xs">
                  <thead className="bg-slate-900/80 uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-3 py-2 font-medium">Rule ID</th>
                      <th className="px-3 py-2 font-medium">Category Tag</th>
                      <th className="px-3 py-2 font-medium">Affected Rows</th>
                      <th className="px-3 py-2 font-medium">Sample Diagnostic</th>
                      <th className="px-3 py-2 font-medium">Action Override</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/80">
                    {manifest.map((row) => {
                      const selected =
                        row.user_category || row.suggested_category;
                      const sample =
                        row.sample_records?.[0] ||
                        (row.message ? { message: row.message } : null);
                      return (
                        <tr key={row.rule_id} data-rule-id={row.rule_id}>
                          <td className="px-3 py-2 font-mono text-cyan-300">
                            {row.rule_id}
                          </td>
                          <td className="px-3 py-2">
                            <span
                              className="inline-flex rounded-md bg-violet-500/15 px-2 py-1 font-mono text-[10px] text-violet-200 ring-1 ring-violet-500/30"
                              data-testid={`category-badge-${row.rule_id}`}
                            >
                              {selected}
                            </span>
                          </td>
                          <td className="px-3 py-2 font-mono text-slate-300">
                            {row.affected_rows === 0 || row.is_file_level ? (
                              <span
                                className="inline-flex rounded-md bg-rose-500/15 px-2 py-1 text-[10px] font-semibold text-rose-200 ring-1 ring-rose-500/30"
                                data-testid={`file-level-${row.rule_id}`}
                              >
                                File-level Impact
                              </span>
                            ) : (
                              formatRowCount(row.affected_rows)
                            )}
                          </td>
                          <td className="max-w-[220px] px-3 py-2 font-mono text-[10px] text-slate-400">
                            {sample
                              ? JSON.stringify(sample).slice(0, 120)
                              : "—"}
                          </td>
                          <td className="px-3 py-2">
                            <select
                              className="w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-200"
                              value={selected}
                              aria-label={`Category for ${row.rule_id}`}
                              data-testid={`category-select-${row.rule_id}`}
                              onChange={(e) =>
                                void onCategoryChange(
                                  row.rule_id,
                                  e.target.value as QuarantineCategory
                                )
                              }
                            >
                              {QUARANTINE_CATEGORIES.map((cat) => (
                                <option key={cat} value={cat}>
                                  {cat}
                                </option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {highlights.length > 0 && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-950/30 p-3">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-rose-300">
                Failing sub-checks
              </p>
              <ul className="space-y-2">
                {highlights.map((h) => (
                  <li key={h.key} className="font-mono text-xs text-rose-100">
                    <span className="text-rose-300">{h.key}:</span>{" "}
                    {typeof h.value === "string"
                      ? h.value
                      : JSON.stringify(h.value)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              gate_evaluations
            </p>
            <pre className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-cyan-100/90">
              {JSON.stringify(item.gate_evaluations, null, 2)}
            </pre>
          </div>
        </div>

        {releasable && (
          <div className="border-t border-slate-800 px-5 py-4">
            <button
              type="button"
              onClick={() => onDeclareShort(item)}
              className="w-full rounded-lg bg-amber-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-amber-500"
            >
              Declare Short &amp; Release
            </button>
          </div>
        )}
      </aside>
    </div>
  );
}
