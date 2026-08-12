import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdjudicationQueue } from "@/app/adjudication/AdjudicationQueue";
import type { AdjudicationItem } from "@/lib/adjudication";
import { runAirlockDryRun } from "@/lib/api/dryRun";
import { TestBenchDrawer } from "@/app/properties/setup/components/TestBenchDrawer";
import type {
  FeedContractForm,
  PropertyFeed,
  PropertyWithFeeds,
} from "@/app/properties/setup/types";

vi.mock("@/lib/engine", () => ({
  getEngineUrl: () => "http://engine.test",
}));

beforeEach(() => {
  vi.restoreAllMocks();
});

function makeItem(
  partial: Partial<AdjudicationItem> &
    Pick<AdjudicationItem, "run_id" | "feed_category" | "overall_outcome">
): AdjudicationItem {
  return {
    property_id: "ESMA.MALAG",
    property_name: "Malaga",
    report_type: "sales_data",
    business_date: "2026-08-11",
    created_at: "2026-08-11T12:00:00Z",
    gate_evaluations: {},
    ...partial,
  };
}

describe("AdjudicationQueue", () => {
  it("test_category_filter_isolation", async () => {
    const user = userEvent.setup();
    const items = [
      makeItem({
        run_id: "pos-1",
        feed_category: "pos",
        overall_outcome: "HOLD_SET",
      }),
      makeItem({
        run_id: "pos-2",
        feed_category: "pos",
        overall_outcome: "QUARANTINE_FILE",
      }),
      makeItem({
        run_id: "pms-1",
        feed_category: "pms",
        overall_outcome: "HOLD_SET",
      }),
      makeItem({
        run_id: "pms-2",
        feed_category: "pms",
        overall_outcome: "HOLD_SET",
      }),
    ];

    render(
      <AdjudicationQueue
        items={items}
        loading={false}
        onDeclareShort={vi.fn()}
        onOpenDetail={vi.fn()}
        onItemsChange={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "POS" }));

    const rows = screen.getAllByRole("row").filter((r) =>
      r.hasAttribute("data-feed-category")
    );
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(row.getAttribute("data-feed-category")).toBe("pos");
    }
  });

  it("test_approve_and_release_click_flow", async () => {
    const user = userEvent.setup();
    const runId = "hold-run-1";
    const items = [
      makeItem({
        run_id: runId,
        feed_category: "pos",
        overall_outcome: "HOLD_SET",
      }),
    ];
    let current = items;
    const onItemsChange = vi.fn((next: AdjudicationItem[]) => {
      current = next;
    });

    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          run_id: runId,
          status: "RELEASED_TO_ETL",
          released_by: "op_402",
          released_at: "2026-08-11T15:00:00Z",
          event: "airlock.run.released",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    const { rerender } = render(
      <AdjudicationQueue
        items={current}
        loading={false}
        operatorId="op_402"
        onDeclareShort={vi.fn()}
        onOpenDetail={vi.fn()}
        onItemsChange={onItemsChange}
      />
    );

    await user.click(screen.getByTestId(`approve-release-${runId}`));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      `http://engine.test/api/v1/airlock/runs/${runId}/release`
    );
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      operator_id: "op_402",
      reason: "Verified manual drop",
    });

    expect(onItemsChange).toHaveBeenCalled();
    const updated = onItemsChange.mock.calls[0][0] as AdjudicationItem[];
    expect(updated[0].overall_outcome).toBe("RELEASED_TO_ETL");

    rerender(
      <AdjudicationQueue
        items={updated}
        loading={false}
        operatorId="op_402"
        onDeclareShort={vi.fn()}
        onOpenDetail={vi.fn()}
        onItemsChange={onItemsChange}
      />
    );

    expect(
      within(screen.getByTestId(`outcome-badge-${runId}`)).getByText(
        "RELEASED_TO_ETL"
      )
    ).toBeInTheDocument();
  });
});

describe("TestBench persistence routing", () => {
  it("test_bench_persistence_checkbox_routing", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "bench-1",
          overall_outcome: "PASS",
          outcome_reason: "ok",
          gate1_report: {
            overall_outcome: "PASS",
            outcome_reason: "ok",
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
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

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

    render(
      <TestBenchDrawer
        open
        property={property}
        feed={feed}
        form={form}
        onClose={vi.fn()}
      />
    );

    await user.click(screen.getByTestId("persist-run-checkbox"));
    await user.click(
      screen.getByRole("button", { name: /Run all four gates/i })
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://engine.test/api/v1/airlock/evaluate");
    const body = JSON.parse(String(init.body));
    expect(body.persist_run).toBe(true);
  });
});

describe("runAirlockDryRun persist flag", () => {
  it("routes to evaluate when persistRun is true", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ run_id: "x", overall_outcome: "PASS" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await runAirlockDryRun({
      propertyId: "ESMA.MALAG",
      filename: "sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
      payloadText: "a|b\n1|2\n",
      contract: { feed_category: "pos" },
      persistRun: true,
      feedCategory: "pos",
    });

    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://engine.test/api/v1/airlock/evaluate"
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).persist_run).toBe(
      true
    );
  });
});
