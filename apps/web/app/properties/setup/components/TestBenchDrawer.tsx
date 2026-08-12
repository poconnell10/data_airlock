"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, FileText, Loader2, Play, Upload, X } from "lucide-react";
import {
  runAirlockDryRun,
  toVerdictLabel,
  type RunAirlockDryRunInput,
} from "@/lib/api/dryRun";
import type { DryRunReport, OverallOutcome, SubEvaluation } from "@/lib/types";
import type {
  FeedContractForm,
  PropertyFeed,
  PropertyWithFeeds,
} from "../types";
import { buildFeedContractYaml, isFileCategory } from "../presets";

const REQUIRED_TOKENS = ["property", "date", "report_type"] as const;

function verdictClass(label: string): string {
  if (label === "RELEASED" || label === "PASS") return "v-pass";
  if (label === "HOLD_SET") return "v-hold";
  if (label === "QUARANTINE" || label === "REJECT") return "v-quar";
  return "v-flag";
}

function badgeClass(outcome: string): string {
  switch (outcome) {
    case "PASS":
    case "RELEASED":
      return "st-pass";
    case "FLAG":
    case "FLAGGED":
      return "st-flag";
    case "HOLD_SET":
      return "st-hold";
    case "QUARANTINE_FILE":
    case "QUARANTINE":
    case "REJECT_FILE":
    case "REJECT":
      return "st-quar";
    default:
      return "st-skip";
  }
}

function findingBadge(passed: boolean, rule: string): string {
  if (passed) return "st-pass";
  if (rule === "atomic_set") return "st-hold";
  return "st-quar";
}

function sampleNamesForFeed(
  feed: PropertyFeed,
  form: FeedContractForm,
  propertyId: string
): string[] {
  const base = form.sampleFilename || "sample.csv";
  const members = form.atomicMembers
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (members.length && isFileCategory(feed.feed_category)) {
    return members.map((m) =>
      base.replace(/^[a-z_]+/, m).includes(m)
        ? base.replace(
            /^(headers_data|sales_data|payments_data|[A-Za-z]+)/,
            m
          )
        : `${m}_${propertyId}_sample.csv`
    );
  }
  return [base];
}

export function TestBenchDrawer({
  open,
  property,
  feed,
  form,
  onClose,
  onToast,
}: {
  open: boolean;
  property: PropertyWithFeeds | null;
  feed: PropertyFeed | null;
  form: FeedContractForm;
  onClose: () => void;
  onToast?: (message: string) => void;
}) {
  const propertyId = property?.property_id ?? "";
  const fileInputRef = useRef<HTMLInputElement>(null);

  const samples = useMemo(
    () => (feed ? sampleNamesForFeed(feed, form, propertyId) : []),
    [feed, form, propertyId]
  );

  const [selected, setSelected] = useState(0);
  const [sourceMode, setSourceMode] = useState<"landing" | "upload" | "paste">(
    "landing"
  );
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [payloadText, setPayloadText] = useState(
    "check_id|amount|guest\nCHK001|33.33|Ada\nCHK002|33.33|Grace\nCHK003|33.34|Alan\nTRL|COUNT|3\nEOF\n"
  );
  const [testFilename, setTestFilename] = useState(
    () =>
      form.sampleFilename ||
      "sales_data_ESMA.MALAG_2026-08-11__a91f.csv"
  );
  const router = useRouter();
  const [isExecuting, setIsExecuting] = useState(false);
  const [persistRun, setPersistRun] = useState<boolean>(false);
  const [lastRunPersisted, setLastRunPersisted] = useState(false);
  const [isPersisting, setIsPersisting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [persistError, setPersistError] = useState<string | null>(null);
  const [report, setReport] = useState<DryRunReport | null>(null);

  const sampleFilename = samples[selected] || form.sampleFilename || "sample.csv";
  const activeFilename =
    sourceMode === "paste"
      ? testFilename
      : uploadFile?.name || sampleFilename;
  const s3Key = feed ? `${feed.s3_prefix}${sampleFilename}` : null;

  const onPickFile = (file: File | null) => {
    setUploadFile(file);
    setReport(null);
    setError(null);
    setPersistError(null);
    if (file) {
      setSourceMode("upload");
      void file.text().then((t) => setPayloadText(t)).catch(() => undefined);
    }
  };

  const resolveRunInput = (
    persist: boolean
  ): RunAirlockDryRunInput | null => {
    if (!feed || !property) return null;
    const contract = buildFeedContractYaml(form, {
      propertyId,
      feedCategory: feed.feed_category,
      presetId: feed.preset_id,
      s3Prefix: feed.s3_prefix,
    });
    const common = {
      propertyId,
      contract,
      persistRun: persist,
      feedCategory: feed.feed_category,
    };
    if (sourceMode === "upload" && uploadFile) {
      return {
        ...common,
        file: uploadFile,
        s3Key: null,
        filename: uploadFile.name,
        path: `${feed.s3_prefix}${uploadFile.name}`,
        presentBatchFilenames: [
          uploadFile.name,
          ...samples.filter((s) => s !== uploadFile.name),
        ],
      };
    }
    if (sourceMode === "paste") {
      const name = testFilename.trim() || sampleFilename;
      return {
        ...common,
        file: null,
        s3Key: null,
        filename: name,
        path: `${feed.s3_prefix}${name}`,
        payloadText,
        presentBatchFilenames: [
          name,
          ...samples.filter((s) => s !== name),
        ],
      };
    }
    return {
      ...common,
      file: null,
      s3Key: null,
      filename: sampleFilename,
      path: s3Key ?? sampleFilename,
      payloadText,
      presentBatchFilenames: samples,
    };
  };

  const runSafe = async () => {
    const input = resolveRunInput(persistRun);
    if (!input) {
      const msg = "Select a property and feed before running the test bench.";
      setError(msg);
      onToast?.(msg);
      return;
    }

    setIsExecuting(true);
    setError(null);
    try {
      const res = await runAirlockDryRun(input);
      setReport(res);
      setLastRunPersisted(Boolean(persistRun));

      const tokens = res.gate1_report.filename_tokens || {};
      const missing = REQUIRED_TOKENS.filter((k) => !tokens[k]);
      if (missing.length) {
        onToast?.(
          `Gate 1 missing required tokens: ${missing.join(", ")} — check filename_regex.`
        );
      } else if (persistRun) {
        onToast?.(
          `Persisted to Adjudication Queue · ${toVerdictLabel(res.overall_outcome)} · ${res.run_id}`
        );
      } else if (res.overall_outcome === "PASS") {
        onToast?.(`Dry-run ${toVerdictLabel(res.overall_outcome)}`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Dry-run failed";
      setError(msg);
      setReport(null);
      onToast?.(msg);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleOpenInAdjudication = async () => {
    if (!report) return;
    setIsPersisting(true);
    setPersistError(null);
    try {
      if (lastRunPersisted && report.run_id) {
        onClose();
        router.push(
          `/adjudication?run_id=${encodeURIComponent(report.run_id)}`
        );
        return;
      }
      const input = resolveRunInput(true);
      if (!input) {
        throw new Error(
          "Select a property and feed before opening adjudication."
        );
      }
      const persisted = await runAirlockDryRun({
        ...input,
        persistRun: true,
        filename: report.filename || input.filename,
        path: report.path ?? input.path,
      });
      if (!persisted.run_id) {
        throw new Error("Evaluate did not return a run_id.");
      }
      setReport(persisted);
      setLastRunPersisted(true);
      onClose();
      router.push(
        `/adjudication?run_id=${encodeURIComponent(persisted.run_id)}`
      );
    } catch (e) {
      const msg =
        e instanceof Error
          ? e.message
          : "Failed to persist run for adjudication";
      setPersistError(msg);
      onToast?.(msg);
    } finally {
      setIsPersisting(false);
    }
  };

  const verdict = report ? toVerdictLabel(report.overall_outcome) : null;
  const findings: SubEvaluation[] = report?.gate1_report.evaluations ?? [];
  const tokens = report?.gate1_report.filename_tokens ?? {};
  const missingTokens = REQUIRED_TOKENS.filter((k) => !tokens[k]);

  const gates: Array<{
    key: string;
    name: string;
    outcome: OverallOutcome | string;
    detail: string;
  }> = report
    ? [
        {
          key: "1",
          name: "Gate 1 · Extraction",
          outcome: report.gate1_report.overall_outcome,
          detail: report.gate1_report.outcome_reason,
        },
        {
          key: "2",
          name: "Gate 2 · Anomaly",
          outcome: report.gate2_report.overall_outcome,
          detail: report.gate2_report.outcome_reason,
        },
        {
          key: "3",
          name: "Gate 3 · Quality",
          outcome: report.gate3_report.overall_outcome,
          detail: report.gate3_report.outcome_reason,
        },
        {
          key: "4",
          name: "Gate 4 · Revenue",
          outcome: report.gate4_report.overall_outcome,
          detail: report.gate4_report.outcome_reason,
        },
      ]
    : [];

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
            <div className="t">Live S3 test bench</div>
            <div className="s">
              Dry-run Gates 1–4 against an uploaded file or a sample landing key.
              Read-only — no transformation, no save, no downstream release.
            </div>
          </div>
          <button type="button" className="x" onClick={onClose} aria-label="Close">
            <X />
          </button>
        </div>

        <div className="dbd">
          <div className="fk">Source</div>
          <div className="cats" style={{ marginBottom: 10 }}>
            {(
              [
                ["landing", "Landing key"],
                ["upload", "Upload file"],
                ["paste", "Paste payload"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={`cat ${sourceMode === id ? "on" : ""}`}
                onClick={() => setSourceMode(id)}
              >
                {label}
              </button>
            ))}
          </div>

          {sourceMode === "upload" && (
            <>
              <div
                className={`drop ${dragOver ? "over" : ""}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  const f = e.dataTransfer.files?.[0];
                  if (f) onPickFile(f);
                }}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    fileInputRef.current?.click();
                  }
                }}
              >
                <Upload />
                <b>
                  {uploadFile
                    ? uploadFile.name
                    : "Drop a file here or click to browse"}
                </b>
                <div className="p">{feed?.s3_prefix ?? "—"}</div>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                style={{ display: "none" }}
                onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
              />
            </>
          )}

          {sourceMode === "landing" && (
            <>
              <div className="fk">Files in cohort · landing prefix</div>
              <div className="flist">
                {samples.map((name, i) => (
                  <button
                    key={name}
                    type="button"
                    className={`fitem ${i === selected ? "on" : ""}`}
                    onClick={() => {
                      setSelected(i);
                      setUploadFile(null);
                    }}
                  >
                    <FileText />
                    <span className="fn">{name}</span>
                    <span className="fm">
                      {i === selected ? "active" : "batch"}
                    </span>
                  </button>
                ))}
                {!samples.length && (
                  <div className="empty">
                    No sample filenames on this feed yet.
                  </div>
                )}
              </div>
            </>
          )}

          {sourceMode === "paste" && (
            <>
              <div className="f" style={{ marginBottom: 12 }}>
                <label
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    color: "var(--mut-2)",
                    display: "block",
                    marginBottom: 6,
                  }}
                >
                  Simulated Filename
                </label>
                <input
                  className="mono"
                  type="text"
                  value={testFilename}
                  onChange={(e) => setTestFilename(e.target.value)}
                  placeholder="e.g. sales_data_ESMA.MALAG_2026-08-11__a91f.csv"
                  disabled={isExecuting}
                  style={{
                    width: "100%",
                    padding: "8px 11px",
                    border: "1px solid var(--line)",
                    borderRadius: 8,
                    fontFamily: "var(--mono)",
                    fontSize: 12.5,
                  }}
                />
              </div>
              <div className="f" style={{ marginTop: 12 }}>
                <label
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: "0.09em",
                    textTransform: "uppercase",
                    color: "var(--mut-2)",
                    display: "block",
                    marginBottom: 6,
                  }}
                >
                  Raw Payload
                </label>
                <textarea
                  value={payloadText}
                  onChange={(e) => setPayloadText(e.target.value)}
                  placeholder="Paste pipe, comma, or tab delimited raw CSV content here..."
                  rows={8}
                  disabled={isExecuting}
                  style={{
                    width: "100%",
                    fontFamily: 'var(--mono, "JetBrains Mono", monospace)',
                    fontSize: 11.5,
                    lineHeight: 1.5,
                    color: "var(--ink, #141821)",
                    backgroundColor: "#ffffff",
                    border: "1px solid var(--line, #E8EAEF)",
                    borderRadius: 8,
                    padding: "10px 12px",
                    resize: "vertical",
                    whiteSpace: "pre",
                    overflowX: "auto",
                    boxShadow: "inset 0 1px 2px rgba(0,0,0,0.03)",
                  }}
                />
              </div>
            </>
          )}

          {error && !report && <p className="err">{error}</p>}

          {report && verdict && (
            <>
              <div className="fk">Verdict</div>
              <div className={`verdict ${verdictClass(verdict)}`}>
                <div className="vk">Overall outcome</div>
                <div className="vv">{verdict}</div>
                <div className="vd">{report.outcome_reason}</div>
                {verdict !== "RELEASED" && (
                  <button
                    type="button"
                    onClick={() => void handleOpenInAdjudication()}
                    disabled={isPersisting}
                    className="mt-3 inline-flex items-center gap-2 px-3.5 py-1.5 text-xs font-medium text-amber-900 bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded-md transition-colors dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-800 focus:outline-none focus:ring-2 focus:ring-amber-500/20"
                  >
                    <span>
                      {isPersisting
                        ? "Persisting run..."
                        : "Open Quarantined File in Adjudication"}
                    </span>
                    <ArrowRight className="w-3.5 h-3.5 text-amber-700 dark:text-amber-300" />
                  </button>
                )}
                {persistError ? (
                  <p className="err" role="alert" style={{ marginTop: 8 }}>
                    {persistError}
                  </p>
                ) : null}
              </div>

              <div className="fk">Captured tokens</div>
              <div className="toks">
                {(
                  [
                    ...REQUIRED_TOKENS,
                    ...(tokens.hash ? (["hash"] as const) : []),
                  ] as const
                ).map((k) => {
                  const val = tokens[k as keyof typeof tokens];
                  const miss = !val;
                  return (
                    <div key={k} className={`tok ${miss ? "miss" : ""}`}>
                      <span className="tk">{k}</span>
                      <span className="tv">{val || "— missing —"}</span>
                    </div>
                  );
                })}
              </div>
              {missingTokens.length > 0 && (
                <p className="err">
                  Mandatory groups failed regex extraction:{" "}
                  <code className="mono">{missingTokens.join(", ")}</code>. Update
                  the filename pattern so{" "}
                  <code className="mono">(?&lt;property&gt;)</code>,{" "}
                  <code className="mono">(?&lt;date&gt;)</code>, and{" "}
                  <code className="mono">(?&lt;report_type&gt;)</code> resolve.
                </p>
              )}

              <div className="fk">Gate 1 findings</div>
              <div className="gates">
                {findings.map((f) => (
                  <div key={`${f.rule_name}-${f.message}`} className="gr">
                    <div
                      className={`gi ${findingBadge(f.passed, f.rule_name)}-i`}
                    >
                      {f.passed ? "✓" : "!"}
                    </div>
                    <div className="gt">
                      <div className="gn">{f.rule_name}</div>
                      <div className="gd">{f.message}</div>
                    </div>
                    <span
                      className={`bdg2 ${findingBadge(f.passed, f.rule_name)}`}
                    >
                      {f.passed ? "PASS" : "FAIL"}
                    </span>
                  </div>
                ))}
              </div>

              <div className="fk">All gates</div>
              <div className="gates">
                {gates.map((g) => (
                  <div key={g.key} className="gr">
                    <div className={`gi ${badgeClass(g.outcome)}-i`}>{g.key}</div>
                    <div className="gt">
                      <div className="gn">{g.name}</div>
                      <div className="gd">{g.detail}</div>
                    </div>
                    <span className={`bdg2 ${badgeClass(g.outcome)}`}>
                      {g.outcome}
                    </span>
                  </div>
                ))}
              </div>

              <div className="fk">ExtractionRunReport · raw JSON</div>
              <pre>{JSON.stringify(report, null, 2)}</pre>
            </>
          )}
        </div>

        <div className="dft" style={{ flexWrap: "wrap" }}>
          <label
            className="lg"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              cursor: "pointer",
              color: "var(--ink-2)",
              fontSize: 12.5,
              fontWeight: 600,
            }}
          >
            <input
              type="checkbox"
              checked={persistRun}
              onChange={(e) => setPersistRun(e.target.checked)}
              data-testid="persist-run-checkbox"
            />
            Save run result to Adjudication Queue
          </label>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              marginLeft: "auto",
            }}
          >
            <span className="lg">
              POST /api/v1/airlock/{persistRun ? "evaluate" : "dry-run"} ·{" "}
              {activeFilename}
            </span>
            <button
              type="button"
              className="btn pri"
              disabled={
                isExecuting || !feed || (sourceMode === "upload" && !uploadFile)
              }
              onClick={() => void runSafe()}
            >
              {isExecuting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              {isExecuting ? "Running…" : "Run all four gates"}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

export { TestBenchDrawer as LiveS3TestBench };
