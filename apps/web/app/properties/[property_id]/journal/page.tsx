"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  createPropertyJournalEntry,
  fetchPropertyJournal,
  type PropertyJournalEntry,
} from "@/lib/api/journal";
import { PropertyJournalTimeline } from "./PropertyJournalTimeline";

export default function PropertyJournalPage() {
  const params = useParams();
  const propertyId = String(params?.property_id || "");
  const [entries, setEntries] = useState<PropertyJournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const reload = async () => {
    if (!propertyId) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await fetchPropertyJournal(propertyId, { limit: 100 });
      setEntries(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load journal");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propertyId]);

  const onAdd = async () => {
    const content = draft.trim();
    if (!content || !propertyId) return;
    setSaving(true);
    try {
      await createPropertyJournalEntry(propertyId, {
        operator_id: "op_402",
        content,
        note_type: "NOTE_ADDED",
        customer_impact: "NONE",
        lifecycle_event: "NOTE_ADDED",
      });
      setDraft("");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add entry");
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#0b1220] text-slate-100">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <Link
            href="/properties/setup"
            className="text-xs text-slate-400 hover:text-cyan-300"
          >
            ← Back to Property Setup
          </Link>
          <Link
            href="/adjudication"
            className="text-xs text-slate-400 hover:text-cyan-300"
          >
            Adjudication Queue →
          </Link>
        </div>

        {error ? (
          <p className="mb-4 rounded-md border border-rose-800/60 bg-rose-950/40 px-3 py-2 text-sm text-rose-200">
            {error}
          </p>
        ) : null}

        {loading ? (
          <p className="text-sm text-slate-500">Loading journal…</p>
        ) : (
          <PropertyJournalTimeline
            entries={entries}
            propertyId={propertyId}
          />
        )}

        <section className="mt-8 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
          <h2 className="text-sm font-semibold text-slate-200">
            Add property-level note
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Manual journal entries (calls, controller meetings, vendor syncs)
            that are not tied to a single run.
          </p>
          <div className="mt-3 flex gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Phone call with Hotel Controller regarding POS upgrade…"
              className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-cyan-600"
            />
            <button
              type="button"
              className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              disabled={!draft.trim() || saving}
              onClick={() => void onAdd()}
            >
              {saving ? "Saving…" : "Add"}
            </button>
          </div>
        </section>
      </div>
    </main>
  );
}
