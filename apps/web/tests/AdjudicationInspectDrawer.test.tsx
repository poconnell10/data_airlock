import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { AdjudicationInspectDrawer } from "@/app/adjudication/AdjudicationInspectDrawer";
import type { AdjudicationItem } from "@/lib/adjudication";

vi.mock("@/lib/engine", () => ({
  getEngineUrl: () => "http://engine.test",
}));

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("AdjudicationInspectDrawer", () => {
  it("test_renders_readiness_progress_bar_and_manifest", () => {
    const item: AdjudicationItem = {
      run_id: "run-95",
      property_id: "ESMA.MALAG",
      property_name: "Malaga",
      report_type: "sales_data",
      business_date: "2026-08-11",
      overall_outcome: "FLAG",
      created_at: "2026-08-11T12:00:00Z",
      gate_evaluations: {},
      readiness_stats: {
        total_rows: 4910,
        verified_rows: 4689,
        quarantined_rows: 221,
        readiness_pct: 95.5,
        quarantine_pct: 4.5,
      },
      quarantine_manifest: [
        {
          rule_id: "G3_TYPE_CAST_FAIL",
          affected_rows: 221,
          row_indices: [1, 2, 3],
          suggested_category: "DATA_QUALITY_BUG",
          message: "poison values",
          sample_records: [{ amount: "ERR", _row_index: 1 }],
        },
      ],
    };

    render(
      <AdjudicationInspectDrawer
        item={item}
        onClose={vi.fn()}
        onDeclareShort={vi.fn()}
      />
    );

    expect(screen.getByTestId("readiness-pct")).toHaveTextContent("95.5%");
    expect(screen.getByTestId("readiness-bar-ready")).toBeInTheDocument();
    expect(screen.getByTestId("readiness-bar-quarantine")).toBeInTheDocument();

    const badge = screen.getByTestId("category-badge-G3_TYPE_CAST_FAIL");
    expect(badge).toHaveTextContent("DATA_QUALITY_BUG");

    const select = screen.getByTestId(
      "category-select-G3_TYPE_CAST_FAIL"
    ) as HTMLSelectElement;
    expect(select.value).toBe("DATA_QUALITY_BUG");
    expect(
      within(select).getByRole("option", { name: "FALSE_POSITIVE" })
    ).toBeInTheDocument();
  });

  it("test_renders_decision_guidance_for_data_quality_and_false_positive", () => {
    const item: AdjudicationItem = {
      run_id: "run-decision",
      property_id: "ESMA.MALAG",
      property_name: "Malaga",
      report_type: "sales_data",
      business_date: "2026-08-11",
      overall_outcome: "REJECT_FILE",
      created_at: "2026-08-11T12:00:00Z",
      gate_evaluations: {},
      readiness_stats: {
        total_rows: 0,
        verified_rows: 0,
        quarantined_rows: 1,
        readiness_pct: 0,
        quarantine_pct: 100,
      },
      quarantine_manifest: [
        {
          rule_id: "G1_PHYSICAL_INTEGRITY",
          affected_rows: 0,
          row_indices: [],
          suggested_category: "DATA_QUALITY_BUG",
          message: "Physical integrity failed: decode error at byte 40",
          sample_records: [],
          is_file_level: true,
          decision_guidance:
            "File-level physical integrity failure. Data encoding or file format is corrupted.",
        },
        {
          rule_id: "G2_VOLUME_ANOMALY",
          affected_rows: 0,
          row_indices: [],
          suggested_category: "FALSE_POSITIVE",
          user_category: "FALSE_POSITIVE",
          message: "Z-score spike",
          sample_records: [],
          decision_guidance: "Statistical volume threshold breached.",
        },
      ],
    };

    render(
      <AdjudicationInspectDrawer
        item={item}
        onClose={vi.fn()}
        onDeclareShort={vi.fn()}
      />
    );

    expect(screen.getByTestId("decision-guidance-panel")).toBeInTheDocument();
    expect(screen.getByTestId("readiness-pill")).toHaveTextContent(
      "File Rejected"
    );
    expect(screen.getByTestId("readiness-pct")).toHaveTextContent("0.0%");

    expect(
      screen.getByText(
        /Data encoding or format is corrupted\. How should we proceed\?/i
      )
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("action-copy-vendor-G1_PHYSICAL_INTEGRITY")
    ).toHaveTextContent("Copy Vendor Ticket Diagnostic Bundle");
    expect(
      screen.getByTestId("action-confirm-rejection-G1_PHYSICAL_INTEGRITY")
    ).toHaveTextContent("Confirm Rejection");

    expect(
      screen.getByText(
        /Statistical volume\/revenue threshold breached\. Is this anomaly business-valid\?/i
      )
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("action-approve-release-G2_VOLUME_ANOMALY")
    ).toHaveTextContent("Approve & Release (One-Time Override)");
  });

  it("test_renders_unbalanced_revenue_decision_card", () => {
    const item: AdjudicationItem = {
      run_id: "run-g4",
      property_id: "ESMA.MALAG",
      property_name: "Malaga",
      report_type: "sales_data",
      business_date: "2026-08-11",
      overall_outcome: "REJECT_FILE",
      created_at: "2026-08-11T12:00:00Z",
      gate_evaluations: {
        gate_4: {
          overall_outcome: "REJECT_FILE",
          evaluations: [
            {
              rule_name: "sales_vs_tender_balance",
              passed: false,
              message:
                "Financial imbalance detected: Net sales $150.00 vs Tender payments $142.50. Variance: 7.50.",
              details: {
                net_sales: 150,
                tender_payments: 142.5,
                variance: 7.5,
              },
            },
          ],
        },
      },
      readiness_stats: {
        total_rows: 12,
        verified_rows: 0,
        quarantined_rows: 12,
        readiness_pct: 0,
        quarantine_pct: 100,
      },
      quarantine_manifest: [
        {
          rule_id: "G4_FINANCIAL_IMBALANCE",
          affected_rows: 0,
          row_indices: [],
          suggested_category: "UNBALANCED_REVENUE",
          message:
            "Financial imbalance detected: Net sales $150.00 vs Tender payments $142.50. Variance: 7.50.",
          sample_records: [],
          is_file_level: true,
          decision_guidance:
            "Financial balance variance detected between sales and payments tender.",
        },
      ],
    };

    render(
      <AdjudicationInspectDrawer
        item={item}
        onClose={vi.fn()}
        onDeclareShort={vi.fn()}
      />
    );

    expect(
      screen.getByTestId("decision-badge-G4_FINANCIAL_IMBALANCE")
    ).toHaveTextContent("UNBALANCED_REVENUE");
    const card = screen.getByTestId("decision-card-G4_FINANCIAL_IMBALANCE");
    expect(card).toHaveTextContent(/Net sales \(\$150\.00\)/i);
    expect(card).toHaveTextContent(/Tender payments \(\$142\.50\)/i);
    expect(card).toHaveTextContent(/\$7\.50/);
    expect(
      screen.getByTestId("action-declare-short-G4_FINANCIAL_IMBALANCE")
    ).toHaveTextContent("Declare Short ($7.50) & Release");
    expect(screen.getByTestId("audit-notes-panel")).toBeInTheDocument();
  });
});
