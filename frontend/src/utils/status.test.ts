import { describe, expect, it, vi } from "vitest";

import { INACTIVE_STATUSES, readinessVariant, statusToVariant } from "./status";

describe("statusToVariant", () => {
  it("maps known app statuses to correct variants", () => {
    expect(statusToVariant("running")).toBe("success");
    expect(statusToVariant("failed")).toBe("danger");
    expect(statusToVariant("stopped")).toBe("warning");
    expect(statusToVariant("disabled")).toBe("neutral");
    expect(statusToVariant("blocked")).toBe("warning");
    expect(statusToVariant("not_started")).toBe("neutral");
    expect(statusToVariant("starting")).toBe("neutral");
    expect(statusToVariant("stopping")).toBe("neutral");
    expect(statusToVariant("shutting_down")).toBe("neutral");
  });

  it("maps exhausted_dead to danger variant", () => {
    expect(statusToVariant("exhausted_dead")).toBe("danger");
  });

  it("maps exhausted_cooling to warning variant", () => {
    expect(statusToVariant("exhausted_cooling")).toBe("warning");
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

describe("readinessVariant", () => {
  it("returns warning when status is running and not ready", () => {
    expect(readinessVariant("running", false)).toBe("warning");
  });

  it("returns success when status is running and ready", () => {
    expect(readinessVariant("running", true)).toBe("success");
  });

  it("delegates to statusToVariant for non-running statuses", () => {
    expect(readinessVariant("failed", false)).toBe("danger");
    expect(readinessVariant("exhausted_dead", false)).toBe("danger");
    expect(readinessVariant("exhausted_cooling", false)).toBe("warning");
  });
});
