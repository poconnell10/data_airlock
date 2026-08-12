import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LiveS3TestBench } from "@/app/properties/setup/components/TestBenchDrawer";
import type {
  FeedContractForm,
  PropertyFeed,
  PropertyWithFeeds,
} from "@/app/properties/setup/types";

const { pushMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: vi.fn(),
    back: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/",
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/engine", () => ({
  getEngineUrl: () => "http://engine.test",
}));

beforeEach(() => {
  pushMock.mockReset();
  vi.restoreAllMocks();
});

const property: PropertyWithFeeds = {
  id: "p1",
  property_id: "ESMA.MALAG",
  property_name: "Malaga",
  customer_id: null,
  timezone: "Europe/Madrid",
  sla_cutoff_time: "08:00",
  sla_grace_period_mins: 30,
  alert_emails: null,
  slack_channel: null,
  active_contract_id: null,
  s3_bucket: "bucket",
  s3_prefix_pattern: "raw/{property}/",
  property_feeds: [],
};

const feed: PropertyFeed = {
  id: "f1",
  property_id: "ESMA.MALAG",
  feed_category: "pos",
  preset_id: "onesait",
  schedule: "daily",
  sla_cutoff_time: "08:00",
  s3_prefix: "raw/ESMA.MALAG/pos/",
  active_contract_id: null,
};

const form: FeedContractForm = {
  timezone: "Europe/Madrid",
  cutoff: "08:00",
  graceMinutes: 30,
  ledgerBackfill: false,
  ledgerWeekend: false,
  encoding: "UTF-8",
  delimiter: "|",
  lineEnding: "LF",
  filenameRegex:
    "^(?<report_type>[a-z_]+)_(?<property>[A-Z.]+)_(?<date>\\d{4}-\\d{2}-\\d{2})__(?<hash>[a-f0-9]+)\\.csv$",
  sampleFilename: "sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
  headerPatterns: "^check_id\\|",
  footerPatterns: "^EOF",
  ignorePatterns: "",
  declaredCountRegex: "",
  pathAgree: false,
  isAtomic: true,
  atomicMembers: "headers_data,sales_data,payments_data",
  objectFormat: "parquet",
  partitionKey: "",
  watermarkColumn: "",
  partitionPath: "",
  requireCommitMarker: false,
  maxZScore: 3,
  enforceDow: true,
  frozenWindow: true,
  headerVsLine: false,
  salesVsTender: true,
  maxVariance: 0.01,
  alertEmails: "",
  slackChannel: "",
  manifestPrefix: "",
};

function quarantineReport(runId: string) {
  return {
    run_id: runId,
    timestamp: "2026-08-11T12:00:00Z",
    property_id: "ESMA.MALAG",
    filename: "sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
    path: "raw/ESMA.MALAG/pos/sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
    overall_outcome: "QUARANTINE_FILE",
    outcome_reason: "G1: filename tokens incomplete",
    gate1_report: {
      overall_outcome: "QUARANTINE_FILE",
      outcome_reason: "filename tokens incomplete",
      filename_tokens: {
        property: "ESMA.MALAG",
        date: "2026-08-11",
        report_type: "sales_data",
      },
      evaluations: [],
    },
    gate2_report: { overall_outcome: "PASS", outcome_reason: "ok" },
    gate3_report: { overall_outcome: "PASS", outcome_reason: "ok" },
    gate4_report: { overall_outcome: "PASS", outcome_reason: "ok" },
  };
}

describe("LiveS3TestBench", () => {
  it("test_quarantine_verdict_shows_open_in_adjudication_button", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const persistedRunId = "persisted-run-42";

    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input) => {
        const url = String(input);
        const runId = url.includes("/evaluate")
          ? persistedRunId
          : "dry-run-ephemeral";
        return new Response(JSON.stringify(quarantineReport(runId)), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    );

    render(
      <LiveS3TestBench
        open
        property={property}
        feed={feed}
        form={form}
        onClose={onClose}
      />
    );

    await user.click(
      screen.getByRole("button", { name: /Run all four gates/i })
    );

    const openBtn = await screen.findByRole("button", {
      name: /Open Quarantined File in Adjudication/,
    });
    expect(openBtn).toBeInTheDocument();

    await user.click(openBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const evaluateCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/v1/airlock/evaluate")
    );
    expect(evaluateCall).toBeTruthy();
    const body = JSON.parse(String(evaluateCall?.[1]?.body));
    expect(body.persist_run).toBe(true);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
      expect(pushMock).toHaveBeenCalledWith(
        `/adjudication?run_id=${persistedRunId}`
      );
    });
  });

  it("keeps the verdict visible when persist returns 502", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/evaluate")) {
        return new Response(
          JSON.stringify({
            detail:
              "Failed to persist run report to adjudication queue: PGRST204",
          }),
          { status: 502, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response(JSON.stringify(quarantineReport("dry-run-ephemeral")), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    render(
      <LiveS3TestBench
        open
        property={property}
        feed={feed}
        form={form}
        onClose={onClose}
      />
    );

    await user.click(
      screen.getByRole("button", { name: /Run all four gates/i })
    );
    const openBtn = await screen.findByRole("button", {
      name: /Open Quarantined File in Adjudication/,
    });
    await user.click(openBtn);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("QUARANTINE")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
  });
});
