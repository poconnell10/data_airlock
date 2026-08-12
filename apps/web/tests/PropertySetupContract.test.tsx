import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PropertySetupPage from "@/app/properties/setup/page";
import type {
  CustomerTree,
  PropertyFeed,
  PropertyWithFeeds,
} from "@/app/properties/setup/types";
import { formFromPreset } from "@/app/properties/setup/presets";

const exportContractToYaml = vi.fn();
const saveAirlockContract = vi.fn();
const fetchCustomerTree = vi.fn();
const fetchContract = vi.fn();
const updateFeed = vi.fn();
const createPropertyWithFirstFeed = vi.fn();
const createFeed = vi.fn();

vi.mock("@/lib/contracts/schema", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/contracts/schema")
  >("@/lib/contracts/schema");
  return {
    ...actual,
    exportContractToYaml: (...args: unknown[]) => exportContractToYaml(...args),
  };
});

vi.mock("@/lib/api/contracts", () => ({
  saveAirlockContract: (...args: unknown[]) => saveAirlockContract(...args),
  fetchAirlockContract: vi.fn(),
}));

vi.mock("@/lib/api/properties", () => ({
  isSupabaseConfigured: () => true,
  fetchCustomerTree: (...args: unknown[]) => fetchCustomerTree(...args),
  fetchContract: (...args: unknown[]) => fetchContract(...args),
  updateFeed: (...args: unknown[]) => updateFeed(...args),
  createPropertyWithFirstFeed: (...args: unknown[]) =>
    createPropertyWithFirstFeed(...args),
  createFeed: (...args: unknown[]) => createFeed(...args),
  updateProperty: vi.fn(),
  saveFeedContract: vi.fn(),
}));

vi.mock("@/lib/engine", () => ({
  getEngineUrl: () => "http://engine.test",
}));

function makeTree(opts?: { activeContractId?: string | null }): CustomerTree[] {
  const feed: PropertyFeed = {
    id: "feed-pos-1",
    property_id: "ESMA.MALAG",
    feed_category: "pos",
    preset_id: "onesait",
    schedule: "daily",
    sla_cutoff_time: "07:00:00",
    s3_prefix: "s3://ing-airlock/raw/ESMA.MALAG/pos/",
    active_contract_id: opts?.activeContractId ?? null,
  };
  const property: PropertyWithFeeds = {
    id: "prop-uuid-1",
    property_id: "ESMA.MALAG",
    property_name: "Malaga Eurobuilding",
    customer_id: "cust-1",
    timezone: "Europe/Madrid",
    sla_cutoff_time: "07:00:00",
    sla_grace_period_mins: 60,
    alert_emails: ["ops@example.com"],
    slack_channel: "#data-ops-alerts",
    active_contract_id: opts?.activeContractId ?? null,
    s3_bucket: "ing-airlock",
    s3_prefix_pattern: "s3://ing-airlock/raw/ESMA.MALAG/pos/",
    property_feeds: [feed],
  };
  return [
    {
      id: "cust-1",
      customer_code: "NH",
      customer_name: "NH Hotels",
      properties: [property],
    },
  ];
}

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.clearAllMocks();
  fetchCustomerTree.mockResolvedValue(makeTree());
  fetchContract.mockResolvedValue(null);
  updateFeed.mockImplementation(async (_id: string, patch: unknown) => ({
    ...makeTree()[0].properties[0].property_feeds[0],
    ...(patch as object),
  }));
  saveAirlockContract.mockImplementation(async () => {
    // After publish, reload should see a linked ingestion contract.
    fetchCustomerTree.mockResolvedValue(
      makeTree({ activeContractId: "ing-contract-1" })
    );
    fetchContract.mockResolvedValue({
      id: "ing-contract-1",
      profile_id: "onesait",
      version: "2.0",
      file_format: "delimited_text",
      contract_yaml: {
        gate_2: { max_z_score: 3 },
        gate_4: { max_variance: 0.01 },
        filename: { pattern: "^(?P<report_type>[a-z_]+)_.*\\.csv$" },
        atomic_set: {
          is_multi_file: true,
          required_endpoints: ["headers_data", "sales_data", "payments_data"],
        },
        file_format: { encoding: "utf-8", delimiter: "|" },
        schedule: {
          timezone: "Europe/Madrid",
          sla_cutoff_time: "07:00",
          grace_period_minutes: 60,
        },
      },
    });
    return {
      id: "ac-1",
      property_id: "ESMA.MALAG",
      feed_id: "feed-pos-1",
      status: "published",
      version: "2.0",
      updated_at: "2026-08-11T22:00:00Z",
      contract_yaml: {},
    };
  });
  exportContractToYaml.mockImplementation((state) => {
    const filename = `contract_${state.propertyId}_${state.systemPreset}_pos.yaml`;
    if (typeof URL.createObjectURL === "function") {
      URL.createObjectURL(
        new Blob(["version: '2.0'\n"], { type: "application/x-yaml" })
      );
    }
    return {
      filename,
      yaml: "version: '2.0'\n",
      contract: { version: "2.0" },
    };
  });

  vi.stubGlobal(
    "URL",
    class {
      static createObjectURL = vi.fn(
        () => "blob:http://localhost/contract.yaml"
      );
      static revokeObjectURL = vi.fn();
    }
  );
});

describe("PropertySetupContract", () => {
  it("test_header_primary_actions_top_right", async () => {
    render(<PropertySetupPage />);

    await waitFor(() => {
      expect(screen.getByTestId("property-setup-header")).toBeInTheDocument();
    });

    const primary = screen.getByTestId("property-header-primary-actions");
    const secondary = screen.getByTestId("property-header-secondary-actions");

    expect(
      within(primary).getByRole("button", { name: /Save airlock contract/i })
    ).toBeInTheDocument();
    expect(
      within(primary).getByRole("button", { name: /Export profile YAML/i })
    ).toBeInTheDocument();
    expect(
      within(secondary).getByTestId("journal-history-link")
    ).toBeInTheDocument();
    expect(
      within(secondary).getByRole("button", {
        name: /Test against live S3 file/i,
      })
    ).toBeInTheDocument();
  });

  it("test_export_yaml_triggers_download", async () => {
    const user = userEvent.setup();
    render(<PropertySetupPage />);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Export profile YAML/i })
      ).toBeEnabled();
    });

    await user.click(
      screen.getByRole("button", { name: /Export profile YAML/i })
    );

    expect(exportContractToYaml).toHaveBeenCalledTimes(1);
    const arg = exportContractToYaml.mock.calls[0][0];
    expect(arg.propertyId).toBe("ESMA.MALAG");
    expect(arg.systemPreset).toBe("onesait");
    expect(arg.form.filenameRegex).toContain("report_type");

    const result = exportContractToYaml.mock.results[0].value as {
      filename: string;
    };
    expect(result.filename).toMatch(/\.yaml$/);
    expect(result.filename).toContain("ESMA.MALAG");

    await waitFor(() => {
      expect(
        screen.getByText(/Exported contract YAML for ESMA\.MALAG/)
      ).toBeInTheDocument();
    });
  });

  it("test_save_contract_persists_state_and_shows_toast", async () => {
    const user = userEvent.setup();
    const { container } = render(<PropertySetupPage />);

    await waitFor(() => {
      expect(
        within(container).getByTestId("contract-status")
      ).toHaveTextContent("contract · draft");
    });

    await user.click(
      within(container).getByRole("button", {
        name: /Save airlock contract/i,
      })
    );

    await waitFor(() => {
      expect(saveAirlockContract).toHaveBeenCalledTimes(1);
    });

    const payload = saveAirlockContract.mock.calls[0][0];
    expect(payload.propertyId).toBe("ESMA.MALAG");
    expect(payload.feedId).toBe("feed-pos-1");
    expect(payload.engineContract.gate_2).toBeTruthy();
    expect(payload.engineContract.gate_4).toBeTruthy();
    expect(
      payload.contractV2.gates.gate1_extraction.filename_pattern
    ).toBeTruthy();
    expect(
      payload.contractV2.gates.gate1_extraction.atomic_set_members
    ).toEqual(
      expect.arrayContaining(["headers_data", "sales_data", "payments_data"])
    );
    expect(payload.contractV2.gates.gate2_anomaly.zscore_threshold).toBe(
      formFromPreset("onesait").maxZScore
    );
    expect(payload.contractV2.gates.gate4_revenue.tolerance_eur).toBe(
      formFromPreset("onesait").maxVariance
    );

    await waitFor(() => {
      expect(
        within(container).getByTestId("contract-status")
      ).toHaveTextContent("contract · published");
      expect(
        within(container).getByText(
          /Airlock contract successfully published to database\./
        )
      ).toBeInTheDocument();
    });
  });
});
