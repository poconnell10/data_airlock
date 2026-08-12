"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { PropertyJournalEntry } from "@/lib/api/journal";

export type JournalFilter =
  | "ALL"
  | "DECISION_REASON"
  | "VENDOR_ESCALATION"
  | "HIGH_IMPACT";

const FILTERS: Array<{ id: JournalFilter; label: string }> = [
  { id: "ALL", label: "All Entries" },
  { id: "DECISION_REASON", label: "Decision Reasons" },
  { id: "VENDOR_ESCALATION", label: "Vendor Escalations" },
  { id: "HIGH_IMPACT", label: "High Customer Impact" },
];

function impactPill(impact: string): { label: string; className: string } {
  if (impact === "CUSTOMER_NOTIFIED" || impact === "HIGH") {
    return {
      label: impact === "CUSTOMER_NOTIFIED" ? "Customer Notified" : "High Impact",
      className: "bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/40",
    };
  }
  if (impact === "MEDIUM" || impact === "LOW") {
    return {
      label: "Internal Ops",
      className: "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/40",
    };
  }
  return {
    label: "Internal Ops",
    className: "bg-slate-500/15 text-slate-300 ring-1 ring-slate-500/40",
  };
}

function noteTypeBadge(noteType: string): string {
  switch (noteType) {
    case "VENDOR_ESCALATION":
      return "bg-rose-500/15 text-rose-300";
    case "DECISION_REASON":
      return "bg-cyan-500/15 text-cyan-200";
    case "THRESHOLD_ADJUSTMENT":
      return "bg-violet-500/15 text-violet-200";
    case "MEETING_REQUIRED":
      return "bg-amber-500/15 text-amber-200";
    default:
      return "bg-slate-500/15 text-slate-300";
  }
}

function formatDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Unknown date";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

function matchesFilter(
  entry: PropertyJournalEntry,
  filter: JournalFilter
): boolean {
  if (filter === "ALL") return true;
  if (filter === "HIGH_IMPACT") {
    return (
      entry.customer_impact === "HIGH" ||
      entry.customer_impact === "CUSTOMER_NOTIFIED"
    );
  }
  return entry.note_type === filter;
}

export function PropertyJournalTimeline({
  entries,
  propertyId,
  propertyName,
}: {
  entries: PropertyJournalEntry[];
  propertyId: string;
  propertyName?: string;
}) {
  const [filter, setFilter] = useState<JournalFilter>("ALL");

  const filtered = useMemo(
    () => entries.filter((e) => matchesFilter(e, filter)),
    [entries, filter]
  );

  const byDay = useMemo(() => {
    const map = new Map<string, PropertyJournalEntry[]>();
    for (const entry of filtered) {
      const key = formatDay(entry.created_at);
      const list = map.get(key) || [];
      list.push(entry);
      map.set(key, list);
    }
    return Array.from(map.entries());
  }, [filtered]);

  return (
    <div className="journal-shell" data-testid="property-journal-timeline">
      <header className="mb-6">
        <p className="text-xs uppercase tracking-[0.16em] text-slate-500">
          Property Journal &amp; Historical Timeline
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-100">
          {propertyId}
          {propertyName ? (
            <span className="ml-2 text-lg font-normal text-slate-400">
              · {propertyName}
            </span>
          ) : null}
        </h1>
        <div
          className="mt-4 flex flex-wrap gap-2"
          data-testid="journal-filter-bar"
        >
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              data-testid={`journal-filter-${f.id}`}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                filter === f.id
                  ? "bg-cyan-700/25 text-cyan-100 ring-1 ring-cyan-600/50"
                  : "bg-slate-900 text-slate-400 ring-1 ring-slate-700 hover:text-slate-200"
              }`}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </header>

      {byDay.length === 0 ? (
        <p className="rounded-lg border border-slate-800 bg-slate-950/60 px-4 py-8 text-center text-sm text-slate-500">
          No journal entries for this filter.
        </p>
      ) : (
        <div className="space-y-8">
          {byDay.map(([day, dayEntries]) => (
            <section key={day}>
              <h2 className="mb-3 text-sm font-semibold text-slate-300">
                {day}
              </h2>
              <ol className="relative space-y-4 border-l border-slate-800 pl-5">
                {dayEntries.map((entry) => {
                  const impact = impactPill(entry.customer_impact);
                  return (
                    <li
                      key={entry.journal_id}
                      className="relative"
                      data-testid="journal-entry"
                      data-note-type={entry.note_type}
                    >
                      <span className="absolute -left-[1.4rem] top-1.5 h-2.5 w-2.5 rounded-full bg-cyan-500 ring-4 ring-[#0b1220]" />
                      <article className="rounded-lg border border-slate-800 bg-slate-950/70 p-4">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                          <span className="font-mono text-slate-300">
                            {formatTime(entry.created_at)}
                          </span>
                          <span>·</span>
                          <span
                            className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide ${noteTypeBadge(
                              entry.note_type
                            )}`}
                          >
                            {entry.note_type}
                          </span>
                          {entry.report_type ? (
                            <>
                              <span>·</span>
                              <span>{entry.report_type}</span>
                            </>
                          ) : null}
                          {entry.run_id ? (
                            <>
                              <span>·</span>
                              <span className="font-mono text-[10px]">
                                Run: {entry.run_id.slice(0, 8)}
                              </span>
                            </>
                          ) : null}
                          <span
                            className={`ml-auto rounded-full px-2 py-0.5 text-[10px] ${impact.className}`}
                          >
                            {impact.label}
                          </span>
                        </div>
                        <p className="mt-2 text-xs text-slate-500">
                          Operator:{" "}
                          <span className="font-mono text-slate-300">
                            {entry.operator_id}
                          </span>
                        </p>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                          {entry.content}
                        </p>
                        <p className="mt-2 text-[11px] text-slate-500">
                          Lifecycle: {entry.lifecycle_event}
                          {entry.lifecycle_event === "NOTE_ADDED" &&
                          entry.note_type === "DECISION_REASON"
                            ? " · Adjudication decision"
                            : null}
                        </p>
                        {entry.run_id ? (
                          <Link
                            href={`/adjudication?run_id=${encodeURIComponent(
                              entry.run_id
                            )}`}
                            className="mt-3 inline-block text-xs font-medium text-cyan-300 hover:text-cyan-200"
                          >
                            Inspect Run Payload →
                          </Link>
                        ) : null}
                      </article>
                    </li>
                  );
                })}
              </ol>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
