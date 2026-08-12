"use client";

import { Check, Plus } from "lucide-react";
import type { PropertyFeed } from "../types";
import { categoryOf, presetOf } from "../presets";

export function FeedTabBar({
  feeds,
  activeFeedId,
  onSelect,
  onAddFeed,
}: {
  feeds: PropertyFeed[];
  activeFeedId: string | null;
  onSelect: (feedId: string) => void;
  onAddFeed: () => void;
}) {
  return (
    <div className="feedbar">
      <span className="fbk">Feeds for this property</span>
      <div className="ftabs">
        {feeds.map((f) => {
          const on = f.id === activeFeedId;
          const cat = categoryOf(f.feed_category);
          const preset = presetOf(f.preset_id);
          return (
            <button
              key={f.id}
              type="button"
              className={`ftab ${on ? "on" : ""}`}
              onClick={() => onSelect(f.id)}
            >
              {on && <Check className="h-3 w-3" strokeWidth={3} />}
              <span className="fc">{cat.name}</span>
              {preset?.name ?? f.preset_id} · {(f.schedule || "daily").toLowerCase()}
            </button>
          );
        })}
        <button type="button" className="ftab add" onClick={onAddFeed}>
          <Plus className="h-3.5 w-3.5" strokeWidth={2.6} />
          Add feed
        </button>
      </div>
    </div>
  );
}
