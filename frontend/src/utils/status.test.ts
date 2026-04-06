import { describe, expect, it, vi } from "vitest";
import { statusToVariant, errorRateToVariant, INACTIVE_STATUSES } from "./status";

describe("statusToVariant", () => {
  it("maps known app statuses to correct variants", () => {
    expect(statusToVariant("running")).toBe("success");
    expect(statusToVariant("failed")).toBe("danger");
    expect(statusToVariant("stopped")).toBe("warning");
    expect(statusToVariant("disabled")).toBe("neutral");
    expect(statusToVariant("blocked")).toBe("warning");
    expect(statusToVariant("starting")).toBe("neutral");
    expect(statusToVariant("shutting_down")).toBe("neutral");
  });

  it("returns neutral and warns for unknown status", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(statusToVariant("exploding")).toBe("neutral");
    expect(warnSpy).toHaveBeenCalledWith('Unknown status: "exploding"');
    warnSpy.mockRestore();
  });
});

describe("INACTIVE_STATUSES", () => {
  it("contains exactly the intentionally non-active statuses", () => {
    expect(INACTIVE_STATUSES).toEqual(new Set(["stopped", "disabled", "shutting_down"]));
  });

  it("does not include failure states that need attention", () => {
    expect(INACTIVE_STATUSES.has("running")).toBe(false);
    expect(INACTIVE_STATUSES.has("failed")).toBe(false);
    expect(INACTIVE_STATUSES.has("blocked")).toBe(false);
    expect(INACTIVE_STATUSES.has("starting")).toBe(false);
  });
});

describe("errorRateToVariant", () => {
  it("maps known error rate classes to correct variants", () => {
    expect(errorRateToVariant("good")).toBe("success");
    expect(errorRateToVariant("warn")).toBe("warning");
    expect(errorRateToVariant("bad")).toBe("danger");
  });

  it("returns neutral and warns for unknown class", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(errorRateToVariant("terrible")).toBe("neutral");
    expect(warnSpy).toHaveBeenCalledWith('Unknown error rate class: "terrible"');
    warnSpy.mockRestore();
  });
});
