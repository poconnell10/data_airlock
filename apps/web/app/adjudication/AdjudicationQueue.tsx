"use client";

import { useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  filterAdjudicationItems,
  releaseRun,
  type AdjudicationItem,
  type FeedCategoryFilter,
  type RunOutcomeFilter,
} from "@/lib/adjudication";
import "../properties/setup/setup.css";

const CATEGORY_PILLS: FeedCategoryFilter[] = [
  "ALL",
  "POS",
  "PMS",
  "RESERVATIONS",
  "DATA_LAKE",
  "DATA_WAREHOUSE",
];

const OUTCOME_PILLS: RunOutcomeFilter[] = [
  "ALL",
  "HOLD_SET",
  "QUARANTINE_FILE",
  "REJECT_FILE",
  "FLAGGED",
  "RELEASED",
  "RELEASED_TO_ETL",
];

function outcomeBadge(outcome: string): string {
  switch (outcome) {
    case "QUARANTINE_FILE":
    case "REJECT_FILE":
      return "bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/40";
    case "HOLD_SET":
      return "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/40";
    case "FLAG":
    case "FLAGGED":
      return "bg-violet-500/15 text-violet-200 ring-1 ring-violet-500/40";
    case "RELEASED_TO_ETL":
    case "PASS_OVERRIDDEN":
    case "PASS":
      return "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/40";
    default:
      return "bg-slate-500/15 text-slate-300 ring-1 ring-slate-500/40";
  }
}

function formatArrived(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function categoryLabel(cat: string | null | undefined): string {
  const map: Record<string, string> = {
    pos: "POS",
    pms: "PMS",
    res: "RES",
    reservations: "RES",
    lake: "LAKE",
    data_lake: "LAKE",
    dwh: "DWH",
    data_warehouse: "DWH",
  };
  if (!cat) return "—";
  return map[cat.toLowerCase()] || cat.toUpperCase();
}

export function AdjudicationQueue({
  items,
  loading,
  error,
  operatorId = "op_402",
  onDeclareShort,
  onOpenDetail,
  onItemsChange,
  onToast,
}: {
  items: AdjudicationItem[];
  loading: boolean;
  error?: string | null;
  operatorId?: string;
  onDeclareShort: (item: AdjudicationItem, e?: React.MouseEvent) => void;
  onOpenDetail: (item: AdjudicationItem) => void;
  onItemsChange: (next: AdjudicationItem[]) => void;
  onToast?: (message: string) => void;
}) {
  const [category, setCategory] = useState<FeedCategoryFilter>("ALL");
  const [outcome, setOutcome] = useState<RunOutcomeFilter>("ALL");
  const [releasingId, setReleasingId] = useState<string | null>(null);

  const filtered = useMemo(
    () => filterAdjudicationItems(items, category, outcome),
    [items, category, outcome]
  );

  const onApproveRelease = async (
    item: AdjudicationItem,
    e: React.MouseEvent
  ) => {
    e.stopPropagation();
    setReleasingId(item.run_id);
    try {
      await releaseRun(item.run_id, {
        operator_id: operatorId.trim() || "op_402",
        reason: "Verified manual drop",
      });
      onItemsChange(
        items.map((row) =>
          row.run_id === item.run_id
            ? { ...row, overall_outcome: "RELEASED_TO_ETL" }
            : row
        )
      );
      onToast?.(
        `Run ${item.run_id.slice(0, 8)}… released to ETL (RELEASED_TO_ETL).`
      );
    } catch (err) {
      onToast?.(
        err instanceof Error ? err.message : "Approve & Release failed."
      );
    } finally {
      setReleasingId(null);
    }
  };

  const releasable = (o: string) =>
    o === "HOLD_SET" || o === "QUARANTINE_FILE" || o === "FLAG";

  return (
    <section className="overflow-hidden rounded-xl border border-slate-800 bg-slate-950/60">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-200">Action Queue</h2>
        <span className="font-mono text-xs text-slate-500">
          {filtered.length} shown · {items.length} loaded
        </span>
      </div>

      <div className="space-y-3 border-b border-slate-800 px-4 py-3">
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Feed category
          </p>
          <div className="chips" role="group" aria-label="Feed category filters">
            {CATEGORY_PILLS.map((pill) => (
              <button
                key={pill}
                type="button"
                className={`pchip ${category === pill ? "on" : ""}`}
                aria-pressed={category === pill}
                onClick={() => setCategory(pill)}
              >
                {pill.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Outcome
          </p>
          <div className="chips" role="group" aria-label="Outcome filters">
            {OUTCOME_PILLS.map((pill) => (
              <button
                key={pill}
                type="button"
                className={`pchip ${outcome === pill ? "on" : ""}`}
                aria-pressed={outcome === pill}
                onClick={() => setOutcome(pill)}
              >
                {pill.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-900/80 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">Property</th>
              <th className="px-4 py-3 font-medium">Category</th>
              <th className="px-4 py-3 font-medium">Report Type</th>
              <th className="px-4 py-3 font-medium">Business Date</th>
              <th className="px-4 py-3 font-medium">Outcome</th>
              <th className="px-4 py-3 font-medium">Arrived At</th>
              <th className="px-4 py-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/80">
            {loading && items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-slate-400">
                  <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" />
                  Loading adjudication queue…
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && !error && (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-slate-500">
                  No rows match the current filters.
                </td>
              </tr>
            )}
            {filtered.map((item) => (
              <tr
                key={item.run_id}
                onClick={() => onOpenDetail(item)}
                className="cursor-pointer transition hover:bg-slate-900/70"
                data-feed-category={item.feed_category || ""}
                data-outcome={item.overall_outcome}
              >
                <td className="px-4 py-3">
                  <div className="font-mono text-xs text-cyan-300">
                    {item.property_id}
                  </div>
                  <div className="text-slate-300">{item.property_name}</div>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-300">
                  {categoryLabel(item.feed_category)}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-300">
                  {item.report_type || "—"}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-300">
                  {item.business_date || "—"}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex rounded-md px-2 py-1 font-mono text-[11px] font-medium ${outcomeBadge(
                      item.overall_outcome
                    )}`}
                    data-testid={`outcome-badge-${item.run_id}`}
                  >
                    {item.overall_outcome}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-400">
                  {formatArrived(item.created_at)}
                </td>
                <td className="px-4 py-3">
                  {releasable(item.overall_outcome) && (
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="btn sm"
                        onClick={(e) => onDeclareShort(item, e)}
                      >
                        Declare Short
                      </button>
                      <button
                        type="button"
                        className="btn pri sm"
                        data-testid={`approve-release-${item.run_id}`}
                        disabled={releasingId === item.run_id}
                        onClick={(e) => void onApproveRelease(item, e)}
                      >
                        {releasingId === item.run_id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : null}
                        Approve &amp; Release
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
