"use client";

import { useMemo, useState } from "react";
import { X } from "lucide-react";
import type { CreateFeedInput, FeedCategory, PropertyFeed } from "../types";
import {
  FEED_CATEGORIES,
  defaultPrefix,
  presetsForCategory,
} from "../presets";

export function AddFeedDrawer({
  open,
  propertyId,
  existingFeeds,
  onClose,
  onSubmit,
}: {
  open: boolean;
  propertyId: string;
  existingFeeds: PropertyFeed[];
  onClose: () => void;
  onSubmit: (input: CreateFeedInput) => Promise<void>;
}) {
  const [cat, setCat] = useState<FeedCategory>("pms");
  const [presetId, setPresetId] = useState("opera");
  const [schedule, setSchedule] = useState("Nightly");
  const [cutoff, setCutoff] = useState("03:00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const presets = presetsForCategory(cat);
  const prefix = useMemo(
    () => defaultPrefix(propertyId, cat),
    [propertyId, cat]
  );

  const create = async () => {
    setError(null);
    if (existingFeeds.some((f) => f.feed_category === cat)) {
      setError(
        `A ${cat.toUpperCase()} feed already exists — switch its system preset instead of adding another.`
      );
      return;
    }
    setBusy(true);
    try {
      await onSubmit({
        propertyId,
        feedCategory: cat,
        presetId,
        schedule,
        slaCutoff: cutoff,
        s3Prefix: prefix,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create feed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div
        className={`scrim ${open ? "on" : ""}`}
        onClick={onClose}
        aria-hidden={!open}
      />
      <aside
        className={`drw ${open ? "on" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
      >
        <div className="dhd">
          <div>
            <div className="t">Add feed</div>
            <div className="s">
              A second feed for {propertyId}, with its own contract, schedule and
              thresholds.
            </div>
          </div>
          <button type="button" className="x" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="dbd">
          <div className="f">
            <label>Feed category</label>
            <div className="cats">
              {FEED_CATEGORIES.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`cat ${cat === c.id ? "on" : ""}`}
                  onClick={() => {
                    setCat(c.id);
                    const first = presetsForCategory(c.id)[0];
                    if (first) setPresetId(first.id);
                  }}
                >
                  {c.name}
                </button>
              ))}
            </div>
          </div>
          <div className="f">
            <label>System preset</label>
            <div className="presets">
              {presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`pchip ${presetId === p.id ? "on" : ""}`}
                  onClick={() => setPresetId(p.id)}
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>
          <div className="row two">
            <div className="f">
              <label>Delivery schedule</label>
              <select
                value={schedule}
                onChange={(e) => setSchedule(e.target.value)}
              >
                {["Daily", "Nightly", "Hourly", "Continuous"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
            <div className="f">
              <label>Expected cutoff</label>
              <input
                type="time"
                value={cutoff}
                onChange={(e) => setCutoff(e.target.value)}
              />
            </div>
          </div>
          <div className="prev">
            <div className="pk2">Landing storage prefix</div>
            <div className="pv mono">{prefix}</div>
          </div>
          {error && <p className="err">{error}</p>}
        </div>
        <div className="dft">
          <span className="lg">
            The contract opens for editing once the feed is created
          </span>
          <button
            type="button"
            className="btn pri"
            disabled={busy}
            onClick={() => void create()}
          >
            {busy ? "Creating…" : "Create feed"}
          </button>
        </div>
      </aside>
    </>
  );
}
