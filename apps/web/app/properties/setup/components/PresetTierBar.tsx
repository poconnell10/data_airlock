"use client";

import { Check } from "lucide-react";
import type { FeedCategory } from "../types";
import {
  FEED_CATEGORIES,
  presetOf,
  presetsForCategory,
} from "../presets";

export function PresetTierBar({
  category,
  presetId,
  onCategory,
  onPreset,
}: {
  category: FeedCategory;
  presetId: string;
  onCategory: (cat: FeedCategory) => void;
  onPreset: (presetId: string) => void;
}) {
  const presets = presetsForCategory(category);
  const note = presetOf(presetId)?.note ?? "";

  return (
    <div className="presetbar">
      <div className="tier">
        <span className="pk">1 · Feed category</span>
        <div className="cats">
          {FEED_CATEGORIES.map((c) => (
            <button
              key={c.id}
              type="button"
              title={c.full}
              className={`cat ${c.id === category ? "on" : ""}`}
              onClick={() => onCategory(c.id)}
            >
              {c.name}
            </button>
          ))}
        </div>
      </div>
      <div className="tier">
        <span className="pk">2 · System preset</span>
        <div className="presets">
          {presets.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`pchip ${presetId === p.id ? "on" : ""}`}
              onClick={() => onPreset(p.id)}
            >
              {presetId === p.id && (
                <Check className="h-3 w-3" strokeWidth={3} />
              )}
              {p.name}
            </button>
          ))}
        </div>
      </div>
      {note && <div className="pn">{note}</div>}
    </div>
  );
}
