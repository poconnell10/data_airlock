"use client";

import type { FeedCategory, FeedContractForm } from "../types";
import { isFileCategory } from "../presets";
import { ChipList } from "./ChipList";
import { FilenameTokenPreview } from "./FilenameTokenPreview";

const SECTIONS = [
  { id: 0, n: "·", t: "Schedule & SLA", s: "Cutoff, grace, ledger" },
  { id: 1, n: "1", t: "Extraction contract", s: "Stateless landing checks" },
  { id: 2, n: "2", t: "Anomaly detection", s: "Stateful trend checks" },
  { id: 3, n: "3", t: "Data quality", s: "Structure & type rules" },
  { id: 4, n: "4", t: "Revenue reconciliation", s: "Financial balancing" },
  { id: 5, n: "·", t: "Report out & alerts", s: "Routing & manifests" },
] as const;

export function ContractWorkbench({
  category,
  form,
  section,
  onSection,
  onChange,
}: {
  category: FeedCategory;
  form: FeedContractForm;
  section: number;
  onSection: (i: number) => void;
  onChange: (patch: Partial<FeedContractForm>) => void;
}) {
  const file = isFileCategory(category);
  const set = <K extends keyof FeedContractForm>(
    key: K,
    value: FeedContractForm[K]
  ) => onChange({ [key]: value });

  const members = form.atomicMembers
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const noise = form.ignorePatterns
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

  const railSections = SECTIONS.map((s) =>
    s.id === 1 && !file
      ? { ...s, t: "Landing contract", s: "Partition & commit checks" }
      : s
  );

  return (
    <div className="cols">
      <nav className="rail">
        <div className="rk">Airlock contract</div>
        {railSections.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`rn ${section === s.id ? "on" : ""}`}
            onClick={() => onSection(s.id)}
          >
            <span className="num">{s.n}</span>
            <span className="rl2">
              <b>{s.t}</b>
              <i>{s.s}</i>
            </span>
          </button>
        ))}
      </nav>

      <div className="secs">
        {section === 0 && (
          <div className="card">
            <div className="chd">
              <div>
                <div className="t">Schedule &amp; SLA delivery ledger</div>
                <div className="s">
                  The airlock expects one delivery per business day. If nothing
                  lands by the cutoff plus grace, the ledger raises a
                  missing-delivery breach — absence is treated as an event, not
                  silence.
                </div>
              </div>
            </div>
            <div className="cb">
              <div className="row">
                <Field label="Property timezone">
                  <select
                    value={form.timezone}
                    onChange={(e) => set("timezone", e.target.value)}
                  >
                    {[
                      "Europe/Madrid",
                      "Europe/London",
                      "Europe/Amsterdam",
                      "America/New_York",
                      "Asia/Dubai",
                      "Australia/Sydney",
                      "UTC",
                    ].map((tz) => (
                      <option key={tz}>{tz}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Expected daily cutoff">
                  <input
                    type="time"
                    value={form.cutoff}
                    onChange={(e) => set("cutoff", e.target.value)}
                  />
                </Field>
                <Field label="SLA grace period">
                  <div className="unit">
                    <input
                      type="number"
                      min={0}
                      max={720}
                      value={form.graceMinutes}
                      onChange={(e) =>
                        set("graceMinutes", Number(e.target.value) || 0)
                      }
                    />
                    <span className="u">min</span>
                  </div>
                </Field>
              </div>
              <div className="grp">
                <div className="gk">Ledger behaviour</div>
                <div className="tglist">
                  <Toggle
                    on={form.ledgerBackfill}
                    onClick={() => set("ledgerBackfill", !form.ledgerBackfill)}
                    title="Accept late backfill"
                    desc="A delivery arriving after the breach still processes, and the ledger records both the breach and the recovery."
                  />
                  <Toggle
                    on={form.ledgerWeekend}
                    onClick={() => set("ledgerWeekend", !form.ledgerWeekend)}
                    title="Expect deliveries seven days a week"
                    desc="Off for properties that only transmit on trading days. Affects which dates count as missing."
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {section === 1 && (
          <div className="card">
            <div className="chd">
              <div>
                <div className="t">
                  <span className="gtag">Gate 1</span>
                  {file ? "Extraction contract" : "Landing contract"}
                </div>
                <div className="s">
                  {file
                    ? "Stateless landing checks. Everything here can be judged from the file itself — no history required. A file that fails Gate 1 never reaches the stateful gates."
                    : "Stateless landing checks on the delivered partition. There is no filename to assert, so identity comes from the partition path and completeness from the commit marker."}
                </div>
              </div>
              <span className="nomut">Non-mutating</span>
            </div>
            <div className="cb">
              {file ? (
                <>
                  <div className="grp">
                    <div className="gk">Transport &amp; encoding</div>
                    <div className="row">
                      <Field label="Encoding">
                        <select
                          value={form.encoding}
                          onChange={(e) => set("encoding", e.target.value)}
                        >
                          {[
                            "UTF-8",
                            "UTF-8-BOM",
                            "ISO-8859-1",
                            "Windows-1252",
                          ].map((e) => (
                            <option key={e}>{e}</option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Delimiter">
                        <select
                          value={form.delimiter}
                          onChange={(e) => set("delimiter", e.target.value)}
                        >
                          <option value=",">, comma</option>
                          <option value="|">| pipe</option>
                          <option value="\t">{"\\t tab"}</option>
                          <option value=";">; semicolon</option>
                        </select>
                      </Field>
                      <Field label="Line ending">
                        <select
                          value={form.lineEnding}
                          onChange={(e) => set("lineEnding", e.target.value)}
                        >
                          <option value={"\n"}>{"\\n LF"}</option>
                          <option value={"\r\n"}>{"\\r\\n CRLF"}</option>
                        </select>
                      </Field>
                    </div>
                  </div>

                  <div className="grp">
                    <div className="gk">Filename contract</div>
                    <Field label="Regex pattern · named groups">
                      <input
                        className="mono"
                        value={form.filenameRegex}
                        onChange={(e) => set("filenameRegex", e.target.value)}
                      />
                      <div className="hint">
                        Required groups: <b>property</b>, <b>date</b>,{" "}
                        <b>report_type</b>. Optional: <b>hash</b>.
                      </div>
                    </Field>
                    <FilenameTokenPreview
                      pattern={form.filenameRegex}
                      sample={form.sampleFilename}
                      onSampleChange={(v) => set("sampleFilename", v)}
                    />
                  </div>

                  <div className="grp">
                    <div className="gk">Path-to-filename agreement</div>
                    <Toggle
                      on={form.pathAgree}
                      onClick={() => set("pathAgree", !form.pathAgree)}
                      title="Assert directory path agrees with filename tokens"
                      desc="Catches a correct file delivered to the wrong property folder — the failure mode no filename check can see."
                    />
                  </div>

                  <div className="grp">
                    <div className="gk">Line conservation</div>
                    <div className="row two">
                      <Field label="Header patterns">
                        <textarea
                          className="mono"
                          value={form.headerPatterns}
                          onChange={(e) =>
                            set("headerPatterns", e.target.value)
                          }
                        />
                      </Field>
                      <Field label="Footer patterns">
                        <textarea
                          className="mono"
                          value={form.footerPatterns}
                          onChange={(e) =>
                            set("footerPatterns", e.target.value)
                          }
                        />
                      </Field>
                    </div>
                    <Field label="Declared row-count regex">
                      <input
                        className="mono"
                        value={form.declaredCountRegex}
                        onChange={(e) =>
                          set("declaredCountRegex", e.target.value)
                        }
                        placeholder="^TRL\\|COUNT\\|(?<declared_row_count>\\d+)"
                      />
                    </Field>
                  </div>

                  <div className="grp">
                    <div className="gk">Atomic set</div>
                    <Toggle
                      on={form.isAtomic}
                      onClick={() => set("isAtomic", !form.isAtomic)}
                      title="Multi-file atomic set"
                      desc="Hold the cohort until every required endpoint lands for the same property and business date."
                    />
                    {form.isAtomic && (
                      <div className="mt-3">
                        <div className="gk">Required endpoints</div>
                        <ChipList
                          values={members}
                          requiredDot
                          placeholder="e.g. payments_data"
                          onChange={(next) =>
                            set("atomicMembers", next.join(", "))
                          }
                        />
                      </div>
                    )}
                  </div>

                  <div className="grp">
                    <div className="gk">Noise filters</div>
                    <ChipList
                      values={noise}
                      placeholder="e.g. .DS_Store"
                      onChange={(next) =>
                        set("ignorePatterns", next.join("\n"))
                      }
                    />
                  </div>
                </>
              ) : (
                <div className="grp">
                  <div className="gk">Object &amp; partition contract</div>
                  <p className="hint mb-3 max-w-xl">
                    Lake and warehouse feeds have no filename to assert.
                    Identity comes from the partition path and the commit
                    marker, and completeness from the watermark rather than a
                    line count.
                  </p>
                  <div className="row">
                    <Field label="Object format">
                      <select
                        value={form.objectFormat}
                        onChange={(e) => set("objectFormat", e.target.value)}
                      >
                        {["Parquet", "Delta", "Avro", "JSONL"].map((o) => (
                          <option key={o}>{o}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Partition key">
                      <input
                        className="mono"
                        value={form.partitionKey}
                        onChange={(e) => set("partitionKey", e.target.value)}
                      />
                    </Field>
                    <Field label="Watermark column">
                      <input
                        className="mono"
                        value={form.watermarkColumn}
                        onChange={(e) =>
                          set("watermarkColumn", e.target.value)
                        }
                      />
                    </Field>
                  </div>
                  <Field label="Partition path template">
                    <input
                      className="mono"
                      value={form.partitionPath}
                      onChange={(e) => set("partitionPath", e.target.value)}
                    />
                  </Field>
                  <div className="mt-3">
                    <Toggle
                      on={form.requireCommitMarker}
                      onClick={() =>
                        set("requireCommitMarker", !form.requireCommitMarker)
                      }
                      title="Require a commit marker before reading"
                      desc="A partition is only read once _SUCCESS or the Delta commit lands. Without this the airlock can read a partition mid-write."
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {section === 2 && (
          <div className="card">
            <div className="chd">
              <div>
                <div className="t">
                  <span className="gtag">Gate 2</span>Anomaly detection
                </div>
                <div className="s">
                  Stateful trend checks against the 30-day day-of-week baseline.
                  Cold-start properties with fewer than three peers skip z-score
                  rather than dividing by zero.
                </div>
              </div>
              <span className="nomut">Non-mutating</span>
            </div>
            <div className="cb">
              <div className="grp">
                <div className="gk">Volume z-score</div>
                <div className="sld">
                  <input
                    type="range"
                    min={1}
                    max={6}
                    step={0.1}
                    value={form.maxZScore}
                    onChange={(e) =>
                      set("maxZScore", Number(e.target.value) || 3)
                    }
                  />
                  <span className="val">{form.maxZScore.toFixed(1)}</span>
                </div>
                <div className="scale">
                  <span>1.0 tight</span>
                  <span>3.0 default</span>
                  <span>6.0 loose</span>
                </div>
              </div>
              <div className="grp">
                <div className="gk">Enforcement</div>
                <div className="tglist">
                  <Toggle
                    on={form.enforceDow}
                    onClick={() => set("enforceDow", !form.enforceDow)}
                    title="Enforce day-of-week volume baseline"
                    desc="Skip when baseline n &lt; 3 (cold-start)."
                  />
                  <Toggle
                    on={form.frozenWindow}
                    onClick={() => set("frozenWindow", !form.frozenWindow)}
                    title="Frozen date window (30 days)"
                    desc="Reject business dates older than the open ingestion window."
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {section === 3 && (
          <div className="card">
            <div className="chd">
              <div>
                <div className="t">
                  <span className="gtag">Gate 3</span>Data quality
                </div>
                <div className="s">
                  Structure and type rules — required columns, non-null
                  constraints, and mid-stream numeric poison detection.
                </div>
              </div>
              <span className="nomut">Non-mutating</span>
            </div>
            <div className="cb">
              <p className="hint max-w-xl">
                Quality rules ship with the system preset. Use the live test
                bench to validate against a real landing sample before
                publishing.
              </p>
            </div>
          </div>
        )}

        {section === 4 && (
          <div className="card">
            <div className="chd">
              <div>
                <div className="t">
                  <span className="gtag">Gate 4</span>Revenue reconciliation
                </div>
                <div className="s">
                  Financial macro-balancing. The last question before ETL: does
                  the file agree with itself?
                </div>
              </div>
              <span className="nomut">Non-mutating</span>
            </div>
            <div className="cb">
              <div className="grp">
                <div className="gk">Balance assertions</div>
                <div className="tglist">
                  <Toggle
                    on={form.headerVsLine}
                    onClick={() => set("headerVsLine", !form.headerVsLine)}
                    title="Header total equals lines plus tax"
                    desc="Header_Total == Σ(Sales_Items) + Tax"
                  />
                  <Toggle
                    on={form.salesVsTender}
                    onClick={() => set("salesVsTender", !form.salesVsTender)}
                    title="Sales equals tender settlement"
                    desc="Σ(Check_Sales) == Σ(Payments/Tenders)"
                  />
                </div>
              </div>
              <div className="grp">
                <div className="gk">Tolerance</div>
                <Field label="Max allowable variance">
                  <div className="unit">
                    <input
                      type="number"
                      step={0.01}
                      min={0}
                      value={form.maxVariance}
                      onChange={(e) =>
                        set("maxVariance", Number(e.target.value) || 0)
                      }
                    />
                    <span className="u">CUR</span>
                  </div>
                  <div className="hint">
                    Applied per batch, not per check — so rounding cannot
                    accumulate unnoticed.
                  </div>
                </Field>
              </div>
            </div>
          </div>
        )}

        {section === 5 && (
          <div className="card">
            <div className="chd">
              <div>
                <div className="t">Report out &amp; alert escalation</div>
                <div className="s">
                  Every outcome has a destination. An unrouted outcome is an
                  outage nobody hears about.
                </div>
              </div>
            </div>
            <div className="cb">
              <div className="grp">
                <div className="gk">SLA breach recipients</div>
                <div className="row two">
                  <Field label="Alert emails">
                    <input
                      value={form.alertEmails}
                      onChange={(e) => set("alertEmails", e.target.value)}
                      placeholder="ops@example.com, gm@hotel.com"
                    />
                  </Field>
                  <Field label="Slack channel">
                    <input
                      value={form.slackChannel}
                      onChange={(e) => set("slackChannel", e.target.value)}
                    />
                  </Field>
                </div>
              </div>
              <div className="grp">
                <div className="gk">Execution run report</div>
                <Field label="Manifest prefix">
                  <input
                    className="mono"
                    value={form.manifestPrefix}
                    onChange={(e) => set("manifestPrefix", e.target.value)}
                  />
                </Field>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="f">
      <label>{label}</label>
      {children}
    </div>
  );
}

function Toggle({
  on,
  onClick,
  title,
  desc,
}: {
  on: boolean;
  onClick: () => void;
  title: string;
  desc: string;
}) {
  return (
    <button type="button" className={`tg ${on ? "on" : ""}`} onClick={onClick}>
      <span className="sw" />
      <span className="tx">
        <span className="tl">{title}</span>
        <span className="td">{desc}</span>
      </span>
    </button>
  );
}
