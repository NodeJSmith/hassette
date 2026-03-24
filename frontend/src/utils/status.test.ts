import { describe, expect, it, vi } from "vitest";
import { statusToVariant, healthGradeToVariant, errorRateToVariant } from "./status";

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
    expect(warnSpy).toHaveBeenCalledWith('Unknown app status: "exploding"');
    warnSpy.mockRestore();
  });
});

describe("healthGradeToVariant", () => {
  it("maps known health grades to correct variants", () => {
    expect(healthGradeToVariant("excellent")).toBe("success");
    expect(healthGradeToVariant("good")).toBe("success");
    expect(healthGradeToVariant("warning")).toBe("warning");
    expect(healthGradeToVariant("critical")).toBe("danger");
  });

  it("returns neutral and warns for unknown grade", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(healthGradeToVariant("superb")).toBe("neutral");
    expect(warnSpy).toHaveBeenCalledWith('Unknown health grade: "superb"');
    warnSpy.mockRestore();
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
