import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PropertyJournalTimeline } from "@/app/properties/[property_id]/journal/PropertyJournalTimeline";
import type { PropertyJournalEntry } from "@/lib/api/journal";

const ENTRIES: PropertyJournalEntry[] = [
  {
    journal_id: "j1",
    property_id: "ESMA.MALAG",
    run_id: "7e3512df-aaaa-bbbb-cccc-ddddeeeeffff",
    operator_id: "op_402",
    note_type: "DECISION_REASON",
    customer_impact: "LOW",
    lifecycle_event: "NOTE_ADDED",
    content: "Approved $12.50 revenue variance — GM confirmed late posting.",
    report_type: "POS Check Detail",
    created_at: "2026-08-12T15:15:00.000Z",
  },
  {
    journal_id: "j2",
    property_id: "ESMA.MALAG",
    run_id: "a91f3b20-1111-2222-3333-444455556666",
    operator_id: "op_108",
    note_type: "VENDOR_ESCALATION",
    customer_impact: "CUSTOMER_NOTIFIED",
    lifecycle_event: "VENDOR_TICKET_OPENED",
    content:
      "Opened ticket #8841 with Micros POS team regarding UTF-8 encoding crash.",
    report_type: "Daily Sales",
    created_at: "2026-08-12T13:30:00.000Z",
  },
];

describe("PropertyJournalTimeline", () => {
  it("test_renders_property_journal_timeline_and_filters", async () => {
    const user = userEvent.setup();
    render(
      <PropertyJournalTimeline
        entries={ENTRIES}
        propertyId="ESMA.MALAG"
        propertyName="Hotel Malaga Esmeralda"
      />
    );

    expect(
      screen.getByTestId("property-journal-timeline")
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("journal-entry")).toHaveLength(2);

    await user.click(screen.getByTestId("journal-filter-VENDOR_ESCALATION"));

    const visible = screen.getAllByTestId("journal-entry");
    expect(visible).toHaveLength(1);
    expect(visible[0]).toHaveAttribute("data-note-type", "VENDOR_ESCALATION");
    expect(screen.getByText(/ticket #8841/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/Approved \$12\.50 revenue variance/i)
    ).not.toBeInTheDocument();
  });
});
