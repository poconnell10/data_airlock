"use client";

import type { AdjudicationItem } from "@/lib/adjudication";
import type {
  QuarantineCategory,
  QuarantineManifestItem,
} from "@/lib/types/airlock";
import "../properties/setup/setup.css";

export type DecisionAction =
  | "copy_vendor_bundle"
  | "confirm_rejection"
  | "approve_release"
  | "approve_autotune"
  | "overwrite_baseline"
  | "keep_original"
  | "approve_exception"
  | "escalate_controller"
  | "declare_short_release"
  | "reject_escalate_audit"
  | "flag_for_sync";

function parseMoneyAmounts(message: string): {
  netSales?: number;
  tender?: number;
  variance?: number;
} {
  const num = "([0-9]+(?:\\.[0-9]+)?)";
  const sales =
    message.match(new RegExp(`Net sales\\s*\\$?\\s*${num}`, "i")) ||
    message.match(new RegExp(`Header total\\s*\\$?\\s*${num}`, "i"));
  const tender =
    message.match(new RegExp(`Tender payments\\s*\\$?\\s*${num}`, "i")) ||
    message.match(new RegExp(`Line sum\\s*\\$?\\s*${num}`, "i"));
  const variance = message.match(new RegExp(`Variance:\\s*\\$?\\s*${num}`, "i"));
  const toNum = (m: RegExpMatchArray | null) =>
    m ? Number(m[1]) : undefined;
  const net = toNum(sales);
  const ten = toNum(tender);
  let vari = toNum(variance);
  if ((vari == null || Number.isNaN(vari)) && net != null && ten != null) {
    vari = Math.abs(net - ten);
  }
  return {
    netSales: net != null && !Number.isNaN(net) ? net : undefined,
    tender: ten != null && !Number.isNaN(ten) ? ten : undefined,
    variance: vari != null && !Number.isNaN(vari) ? vari : undefined,
  };
}

function effectiveCategory(item: QuarantineManifestItem): QuarantineCategory {
  if (item.user_category) return item.user_category;
  if (
    item.rule_id === "G4_FINANCIAL_IMBALANCE" ||
    item.rule_id === "G4_UNBALANCED_HEADER" ||
    /Financial imbalance|Net sales.*Tender/i.test(item.message || "")
  ) {
    return "UNBALANCED_REVENUE";
  }
  if (
    item.is_file_level ||
    item.rule_id === "G1_PHYSICAL_INTEGRITY" ||
    /physical|decode/i.test(item.message || "")
  ) {
    return "DATA_QUALITY_BUG";
  }
  return item.suggested_category;
}

function guidanceCopy(
  category: QuarantineCategory,
  item: QuarantineManifestItem
): { question: string; why: string } {
  const money = parseMoneyAmounts(item.message || "");
  switch (category) {
    case "UNBALANCED_REVENUE": {
      const sales = money.netSales?.toFixed(2) ?? "—";
      const tender = money.tender?.toFixed(2) ?? "—";
      const variance = money.variance?.toFixed(2) ?? "—";
      return {
        question: `Net sales ($${sales}) differs from Tender payments ($${tender}) by $${variance}. How should this variance be handled?`,
        why:
          item.decision_guidance ||
          item.message ||
          "Financial balance variance detected between sales and payments tender.",
      };
    }
    case "DATA_QUALITY_BUG":
      return {
        question:
          "Data encoding or format is corrupted. How should we proceed?",
        why: "Physical integrity / data-quality checks failed before rows could be trusted.",
      };
    case "FALSE_POSITIVE":
      return {
        question:
          "Statistical volume/revenue threshold breached. Is this anomaly business-valid?",
        why: "Anomaly detectors flagged a spike or dip that may be a legitimate trading day.",
      };
    case "OVERLAP_DRIFT":
      return {
        question:
          "Certified historical data exists for this date with different checksums. Overwrite baseline?",
        why: "A previously certified payload for this business date disagrees with the new landing.",
      };
    case "BUSINESS_EDGE_CASE":
      return {
        question:
          "Operational exception detected (e.g. zero covers or 100% comp check). Approve as business exception?",
        why:
          item.decision_guidance ||
          "Unusual business transaction pattern detected.",
      };
    default:
      return {
        question: "How should Data Ops adjudicate this quarantine item?",
        why: "Review the diagnostic message and choose a classification or release path.",
      };
  }
}

export function QuarantineDecisionCard({
  item,
  run,
  onAction,
}: {
  item: QuarantineManifestItem;
  run: AdjudicationItem;
  onAction: (action: DecisionAction, row: QuarantineManifestItem) => void;
}) {
  const category = effectiveCategory(item);
  const copy = guidanceCopy(category, item);
  const money = parseMoneyAmounts(item.message || "");
  const varianceLabel =
    money.variance != null ? `$${money.variance.toFixed(2)}` : "$—";

  return (
    <article
      className="rounded-xl border border-slate-800 bg-slate-950/70 p-4"
      data-testid={`decision-card-${item.rule_id}`}
      data-category={category}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] text-cyan-300">{item.rule_id}</span>
        <span
          className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-[10px] ring-1 ${
            category === "UNBALANCED_REVENUE"
              ? "bg-amber-500/15 text-amber-200 ring-amber-500/40"
              : "bg-violet-500/15 text-violet-200 ring-violet-500/30"
          }`}
          data-testid={`decision-badge-${item.rule_id}`}
        >
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              category === "UNBALANCED_REVENUE" ? "bg-rose-400" : "bg-violet-300"
            }`}
            aria-hidden
          />
          {category}
        </span>
        {(item.is_file_level || item.affected_rows === 0) && (
          <span className="inline-flex rounded-md bg-rose-500/15 px-2 py-0.5 text-[10px] font-semibold text-rose-200 ring-1 ring-rose-500/30">
            File-level Impact
          </span>
        )}
      </div>

      {category === "UNBALANCED_REVENUE" && (
        <div
          className="mb-3 rounded-lg border border-amber-500/30 bg-amber-950/30 px-3 py-2 font-mono text-[11px] text-amber-100"
          data-testid={`diagnostic-${item.rule_id}`}
        >
          {item.message ||
            `Net sales $${money.netSales?.toFixed(2) ?? "—"} vs Tender payments $${
              money.tender?.toFixed(2) ?? "—"
            } · Variance ${varianceLabel}`}
        </div>
      )}

      <p className="text-sm font-semibold text-slate-100">{copy.question}</p>
      <p className="mt-1 text-xs text-slate-400">
        <span className="font-semibold text-slate-300">Why: </span>
        {copy.why}
      </p>
      <p className="mt-1 font-mono text-[10px] text-slate-500">
        {run.property_id} · {run.business_date} · {run.report_type}
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        {category === "UNBALANCED_REVENUE" && (
          <>
            <button
              type="button"
              className="btn pri sm"
              data-testid={`action-declare-short-${item.rule_id}`}
              onClick={() => onAction("declare_short_release", item)}
            >
              Declare Short ({varianceLabel}) &amp; Release
            </button>
            <button
              type="button"
              className="btn danger sm"
              data-testid={`action-reject-escalate-${item.rule_id}`}
              onClick={() => onAction("reject_escalate_audit", item)}
            >
              Reject File &amp; Escalate to Audit
            </button>
          </>
        )}

        {(category === "DATA_QUALITY_BUG" ||
          item.rule_id.includes("PHYSICAL")) && (
          <>
            <button
              type="button"
              className="btn sec sm"
              data-testid={`action-copy-vendor-${item.rule_id}`}
              onClick={() => onAction("copy_vendor_bundle", item)}
            >
              Copy Vendor Ticket Diagnostic Bundle
            </button>
            <button
              type="button"
              className="btn danger sm"
              data-testid={`action-confirm-rejection-${item.rule_id}`}
              onClick={() => onAction("confirm_rejection", item)}
            >
              Confirm Rejection
            </button>
          </>
        )}

        {category === "FALSE_POSITIVE" && (
          <>
            <button
              type="button"
              className="btn pri sm"
              data-testid={`action-approve-release-${item.rule_id}`}
              onClick={() => onAction("approve_release", item)}
            >
              Approve &amp; Release (One-Time Override)
            </button>
            <button
              type="button"
              className="btn sec sm"
              data-testid={`action-approve-autotune-${item.rule_id}`}
              onClick={() => onAction("approve_autotune", item)}
            >
              Approve &amp; Auto-Tune Contract Threshold
            </button>
          </>
        )}

        {category === "OVERLAP_DRIFT" && (
          <>
            <button
              type="button"
              className="btn pri sm"
              data-testid={`action-overwrite-${item.rule_id}`}
              onClick={() => onAction("overwrite_baseline", item)}
            >
              Overwrite Certified Date
            </button>
            <button
              type="button"
              className="btn sec sm"
              data-testid={`action-keep-original-${item.rule_id}`}
              onClick={() => onAction("keep_original", item)}
            >
              Keep Original &amp; Discard
            </button>
          </>
        )}

        {category === "BUSINESS_EDGE_CASE" && (
          <>
            <button
              type="button"
              className="btn pri sm"
              data-testid={`action-approve-exception-${item.rule_id}`}
              onClick={() => onAction("approve_exception", item)}
            >
              Approve Exception &amp; Release
            </button>
            <button
              type="button"
              className="btn sec sm"
              data-testid={`action-flag-sync-${item.rule_id}`}
              onClick={() => onAction("flag_for_sync", item)}
            >
              Flag for Sync
            </button>
          </>
        )}
      </div>
    </article>
  );
}
