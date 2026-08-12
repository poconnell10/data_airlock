"use client";

import { useMemo, type ReactNode } from "react";
import { toJsNamedGroups } from "../presets";

const REQUIRED = ["property", "date", "report_type"] as const;

/** Live regex named-group preview — mirrors v2.html `parse()`. */
export function FilenameTokenPreview({
  pattern,
  sample,
  onSampleChange,
}: {
  pattern: string;
  sample: string;
  onSampleChange: (v: string) => void;
}) {
  const result = useMemo(() => {
    const sanitizedRegexPattern = toJsNamedGroups(pattern);
    try {
      const re = new RegExp(sanitizedRegexPattern);
      const m = re.exec(sample);
      if (!m) {
        return {
          ok: false as const,
          error: "This filename would be refused at Gate 1 — the pattern does not match.",
          groups: {} as Record<string, string>,
        };
      }
      const groups = { ...(m.groups || {}) };
      return { ok: true as const, error: null, groups };
    } catch (e) {
      return {
        ok: false as const,
        error: `Pattern is not valid: ${e instanceof Error ? e.message : String(e)}`,
        groups: {} as Record<string, string>,
      };
    }
  }, [pattern, sample]);

  const keys = Array.from(
    new Set([...REQUIRED, ...Object.keys(result.groups)])
  );

  return (
    <div className="tokbox">
      <div className="tokhd">
        <span className="k">Token preview</span>
        <span className="text-[11px] text-[var(--setup-mut-2)]">
          Edit the sample to test the pattern
        </span>
      </div>
      <input
        className="sample"
        value={sample}
        onChange={(e) => onSampleChange(e.target.value)}
      />
      {result.ok && (
        <div className="split">
          {highlightSample(sample, pattern)}
        </div>
      )}
      <div className="toks">
        {keys.map((k) => {
          const val = result.groups[k];
          const miss = !val;
          return (
            <div key={k} className={`tok ${miss ? "miss" : ""}`}>
              <span className="tk">{k}</span>
              <span className="tv">{val || "— missing —"}</span>
            </div>
          );
        })}
      </div>
      <div className={`parse ${result.ok ? "ok" : "bad"}`}>
        {result.ok
          ? "Filename matches — Gate 1 identity tokens resolved."
          : result.error}
      </div>
    </div>
  );
}

function highlightSample(sample: string, pattern: string): ReactNode {
  try {
    const re = new RegExp(toJsNamedGroups(pattern));
    const m = re.exec(sample);
    if (!m || !m.groups) return sample;
    // Simple whole-string coloring by group order in the match
    const parts: ReactNode[] = [];
    let cursor = 0;
    const entries = Object.entries(m.groups).filter(([, v]) => v != null);
    // Sort by appearance in sample
    entries.sort((a, b) => sample.indexOf(a[1]!) - sample.indexOf(b[1]!));
    entries.forEach(([name, value], i) => {
      if (!value) return;
      const idx = sample.indexOf(value, cursor);
      if (idx < 0) return;
      if (idx > cursor) {
        parts.push(
          <span key={`t-${i}`}>{sample.slice(cursor, idx)}</span>
        );
      }
      parts.push(
        <span key={`g-${name}`} className={`sp ${name}`}>
          {value}
        </span>
      );
      cursor = idx + value.length;
    });
    if (cursor < sample.length) {
      parts.push(<span key="tail">{sample.slice(cursor)}</span>);
    }
    return parts.length ? parts : sample;
  } catch {
    return sample;
  }
}
