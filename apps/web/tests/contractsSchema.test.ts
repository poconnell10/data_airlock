import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  buildAirlockContractV2,
  contractFilename,
  exportContractToYaml,
} from "@/lib/contracts/schema";
import { formFromPreset } from "@/app/properties/setup/presets";

describe("AirlockContractV2 schema", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "URL",
      class {
        static createObjectURL = vi.fn(() => "blob:http://localhost/x.yaml");
        static revokeObjectURL = vi.fn();
      }
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds v2 document with gate fields", () => {
    const form = formFromPreset("onesait");
    const doc = buildAirlockContractV2({
      propertyId: "ESMA.MALAG",
      feedCategory: "pos",
      systemPreset: "onesait",
      form,
      updatedAt: "2026-08-11T22:00:00Z",
    });
    expect(doc.version).toBe("2.0");
    expect(doc.metadata.property_id).toBe("ESMA.MALAG");
    expect(doc.gates.gate1_extraction.delimiter).toBe("|");
    expect(doc.gates.gate1_extraction.atomic_set_members).toContain(
      "sales_data"
    );
    expect(doc.gates.gate2_anomaly.zscore_threshold).toBe(3);
    expect(doc.gates.gate4_revenue.tolerance_eur).toBe(0.01);
  });

  it("exportContractToYaml triggers Blob download with .yaml name", () => {
    const click = vi.fn();
    const append = vi.spyOn(document.body, "appendChild");
    const remove = vi.spyOn(HTMLAnchorElement.prototype, "remove").mockImplementation(
      () => undefined
    );
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(click);

    const { filename, yaml } = exportContractToYaml({
      propertyId: "ESMA.MALAG",
      feedCategory: "pos",
      systemPreset: "onesait",
      form: formFromPreset("onesait"),
    });

    expect(filename).toBe(
      contractFilename("ESMA.MALAG", "onesait", "pos")
    );
    expect(filename).toMatch(/\.yaml$/);
    expect(yaml).toContain('version: "2.0"');
    expect(yaml).toContain("gate1_extraction:");
    expect(URL.createObjectURL).toHaveBeenCalled();
    const blobArg = (URL.createObjectURL as unknown as ReturnType<typeof vi.fn>)
      .mock.calls[0][0] as Blob;
    expect(blobArg).toBeInstanceOf(Blob);
    expect(click).toHaveBeenCalled();
    append.mockRestore();
    remove.mockRestore();
  });
});
