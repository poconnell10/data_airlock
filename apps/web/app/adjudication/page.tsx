"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock3,
  Loader2,
  PauseCircle,
  RefreshCw,
  ShieldAlert,
  X,
} from "lucide-react";
import {
  fetchAdjudicationMetrics,
  fetchAdjudicationQueue,
  submitOverride,
  type AdjudicationItem,
  type AdjudicationMetrics,
} from "@/lib/adjudication";
import { AdjudicationInspectDrawer } from "./AdjudicationInspectDrawer";
import { AdjudicationQueue } from "./AdjudicationQueue";

type DrawerMode = "detail" | "override" | null;

export default function AdjudicationPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-[#0b1220] text-slate-100">
          <div className="mx-auto max-w-7xl px-6 py-8 text-sm text-slate-400">
            Loading adjudication queue…
          </div>
        </main>
      }
    >
      <AdjudicationPageContent />
    </Suspense>
  );
}

function AdjudicationPageContent() {
  const [items, setItems] = useState<AdjudicationItem[]>([]);
  const [metrics, setMetrics] = useState<AdjudicationMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const [selected, setSelected] = useState<AdjudicationItem | null>(null);
  const [drawer, setDrawer] = useState<DrawerMode>(null);

  const [operatorId, setOperatorId] = useState("op_402");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const searchParams = useSearchParams();
  const deepLinkRunId = searchParams.get("run_id");
  const autoOpenedRef = useRef<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [queue, mets] = await Promise.all([
        fetchAdjudicationQueue(),
        fetchAdjudicationMetrics(),
      ]);
      setItems(queue);
      setMetrics(mets);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to reach the adjudication API / Supabase."
      );
      setItems([]);
      setMetrics(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!deepLinkRunId || loading) return;
    if (autoOpenedRef.current === deepLinkRunId) return;
    const match = items.find((item) => item.run_id === deepLinkRunId);
    if (!match) return;
    autoOpenedRef.current = deepLinkRunId;
    setSelected(match);
    setDrawer("detail");
    setFormError(null);
  }, [deepLinkRunId, items, loading]);

  const openDetail = (item: AdjudicationItem) => {
    setSelected(item);
    setDrawer("detail");
    setFormError(null);
  };

  const openOverride = (item: AdjudicationItem, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setSelected(item);
    setDrawer("override");
    setReason("");
    setFormError(null);
    setBanner(null);
  };

  const closeDrawer = () => {
    setDrawer(null);
    setSelected(null);
    setFormError(null);
  };

  const onSubmitOverride = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    setFormError(null);
    if (!operatorId.trim()) {
      setFormError("Operator ID is required.");
      return;
    }
    if (reason.trim().length < 10) {
      setFormError("Reason must be at least 10 characters.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await submitOverride({
        run_id: selected.run_id,
        property_id: selected.property_id,
        override_type: "DECLARE_SHORT",
        reason: reason.trim(),
        operator_id: operatorId.trim(),
      });
      setBanner(`Override recorded — ${res.new_run_id} → ${res.status}`);
      closeDrawer();
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Override failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const metricCards = [
    {
      label: "Active Quarantines",
      value: metrics?.active_quarantines ?? 0,
      icon: ShieldAlert,
      accent: "text-rose-300",
    },
    {
      label: "Held Sets",
      value: metrics?.held_sets ?? 0,
      icon: PauseCircle,
      accent: "text-amber-300",
    },
    {
      label: "SLA Breaches",
      value: metrics?.sla_breaches ?? 0,
      icon: Clock3,
      accent: "text-violet-300",
    },
    {
      label: "Overrides Today",
      value: metrics?.overrides_executed_today ?? 0,
      icon: CheckCircle2,
      accent: "text-emerald-300",
    },
  ];

  return (
    <main className="min-h-screen bg-[#0b1220] text-slate-100">
      <div
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          background:
            "radial-gradient(900px 420px at 10% -10%, rgba(14,116,144,0.28), transparent 55%), radial-gradient(700px 380px at 90% 0%, rgba(244,63,94,0.12), transparent 50%)",
        }}
      />

      <div className="relative mx-auto max-w-7xl px-6 py-8">
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-cyan-400/80">
              Data Airlock · Ops
            </p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight text-white">
              Adjudication Queue
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-400">
              Filter blocked landings, declare shorts, or approve 1-click release
              to ETL.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/70 px-3 py-2 text-sm text-slate-200 transition hover:border-cyan-700 hover:text-white"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </header>

        {error && (
          <div
            role="alert"
            className="mb-6 flex items-start gap-3 rounded-lg border border-rose-500/40 bg-rose-950/50 px-4 py-3 text-sm text-rose-100"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">Engine / Supabase unreachable</p>
              <p className="mt-1 text-rose-200/90">{error}</p>
            </div>
          </div>
        )}

        {banner && (
          <div
            role="status"
            className="mb-6 flex items-start justify-between gap-3 rounded-lg border border-emerald-500/40 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-100"
          >
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              <p>{banner}</p>
            </div>
            <button
              type="button"
              onClick={() => setBanner(null)}
              className="text-emerald-200/80 hover:text-white"
              aria-label="Dismiss"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        <section className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {metricCards.map((card) => {
            const Icon = card.icon;
            return (
              <div
                key={card.label}
                className="rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-4 shadow-[0_0_0_1px_rgba(148,163,184,0.04)]"
              >
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    {card.label}
                  </p>
                  <Icon className={`h-4 w-4 ${card.accent}`} aria-hidden />
                </div>
                <p className="mt-3 font-mono text-3xl font-semibold text-white">
                  {loading && !metrics ? "—" : card.value}
                </p>
              </div>
            );
          })}
        </section>

        <AdjudicationQueue
          items={items}
          loading={loading}
          error={error}
          operatorId={operatorId}
          onDeclareShort={openOverride}
          onOpenDetail={openDetail}
          onItemsChange={setItems}
          onToast={setBanner}
        />
      </div>

      {drawer === "detail" && selected && (
        <AdjudicationInspectDrawer
          item={selected}
          operatorId={operatorId}
          onClose={closeDrawer}
          onDeclareShort={(it) => openOverride(it)}
          onItemPatch={(next) => {
            setSelected(next);
            setItems((prev) =>
              prev.map((row) => (row.run_id === next.run_id ? next : row))
            );
          }}
          onToast={setBanner}
        />
      )}

      {drawer === "override" && selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="override-title"
            className="w-full max-w-lg rounded-xl border border-slate-700 bg-[#0d1526] shadow-2xl"
          >
            <div className="flex items-start justify-between border-b border-slate-800 px-5 py-4">
              <div>
                <h3
                  id="override-title"
                  className="text-lg font-semibold text-white"
                >
                  Declare Short &amp; Release
                </h3>
                <p className="mt-1 text-xs text-slate-400">
                  Appends{" "}
                  <span className="font-mono text-emerald-300">
                    PASS_OVERRIDDEN
                  </span>{" "}
                  — original row stays immutable.
                </p>
              </div>
              <button
                type="button"
                onClick={closeDrawer}
                className="rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={onSubmitOverride} className="space-y-4 px-5 py-4">
              <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 font-mono text-xs text-slate-300">
                {selected.property_id} · {selected.report_type} ·{" "}
                {selected.business_date}
                <div className="mt-1 text-slate-500">{selected.run_id}</div>
              </div>

              <div>
                <label
                  className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500"
                  htmlFor="operator_id"
                >
                  Operator ID
                </label>
                <input
                  id="operator_id"
                  value={operatorId}
                  onChange={(e) => setOperatorId(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none ring-cyan-700/30 focus:border-cyan-600 focus:ring-2"
                  placeholder="op_402"
                  required
                />
              </div>

              <div>
                <label
                  className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500"
                  htmlFor="reason"
                >
                  Reason for Override
                </label>
                <textarea
                  id="reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={4}
                  minLength={10}
                  maxLength={500}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none ring-cyan-700/30 focus:border-cyan-600 focus:ring-2"
                  placeholder="Manual journal entry posted by manager…"
                  required
                />
                <p className="mt-1 text-xs text-slate-500">
                  {reason.trim().length}/500 · minimum 10 characters
                </p>
              </div>

              {formError && (
                <div className="flex items-start gap-2 rounded-lg border border-rose-500/40 bg-rose-950/40 px-3 py-2 text-xs text-rose-100">
                  <Ban className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {formError}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={closeDrawer}
                  className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-900"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-60"
                >
                  {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  Confirm Override
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
