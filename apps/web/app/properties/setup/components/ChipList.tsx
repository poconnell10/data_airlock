"use client";

import { useState } from "react";
import { X } from "lucide-react";

export function ChipList({
  values,
  onChange,
  placeholder = "Add…",
  requiredDot,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  requiredDot?: boolean;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const v = draft.trim();
    if (!v || values.includes(v)) return;
    onChange([...values, v]);
    setDraft("");
  };

  return (
    <div>
      <div className="chips">
        {values.map((v) => (
          <span key={v} className={`ch ${requiredDot ? "req" : ""}`}>
            {v}
            <button
              type="button"
              aria-label={`Remove ${v}`}
              onClick={() => onChange(values.filter((x) => x !== v))}
            >
              <X />
            </button>
          </span>
        ))}
      </div>
      <div className="addrow">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
        />
        <button type="button" className="btn sm" onClick={add}>
          Add
        </button>
      </div>
    </div>
  );
}
