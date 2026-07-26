import { describe, expect, it } from "vitest";

import { buildCommonStatCells, type CommonStatInput } from "./stat-cell-builders";

function baseInput(overrides: Partial<CommonStatInput> = {}): CommonStatInput {
  return {
    totalLabel: "Calls",
    total: 10,
    failed: 0,
    avgDurationMs: 1234,
    lastLabel: "2m ago",
    timedOut: 0,
    cancelled: 0,
    threadLeaked: 0,
    suppressedCount: 0,
    droppedCount: 0,
    ...overrides,
  };
}

describe("buildCommonStatCells", () => {
  it("builds the shared cells with no conditional cells when all counts are zero", () => {
    const cells = buildCommonStatCells(baseInput());

    expect(cells).toEqual([
      { label: "Calls", value: 10, tone: undefined },
      { label: "Failed", value: 0, tone: undefined },
      { label: "Err %", value: "0%", tone: undefined },
      { label: "Avg", value: "1.2s" },
      { label: "Last", value: "2m ago" },
    ]);
  });

  it("uses the provided totalLabel", () => {
    const cells = buildCommonStatCells(baseInput({ totalLabel: "Runs", total: 5 }));

    expect(cells[0]).toEqual({ label: "Runs", value: 5, tone: undefined });
  });

  it("marks Failed and Err % with err tone when failed > 0", () => {
    const cells = buildCommonStatCells(baseInput({ failed: 3, total: 10 }));

    const failedCell = cells.find((c) => c.label === "Failed");
    const errRateCell = cells.find((c) => c.label === "Err %");

    expect(failedCell).toEqual({ label: "Failed", value: 3, tone: "err" });
    expect(errRateCell?.tone).toBe("err");
  });

  it("uses lastFieldLabel override when provided", () => {
    const cells = buildCommonStatCells(baseInput({ lastFieldLabel: "Next", lastLabel: "next in 5m" }));

    expect(cells.find((c) => c.label === "Next")).toEqual({ label: "Next", value: "next in 5m" });
    expect(cells.find((c) => c.label === "Last")).toBeUndefined();
  });

  it("omits conditional cells when their counts are zero", () => {
    const cells = buildCommonStatCells(baseInput());
    const labels = cells.map((c) => c.label);

    expect(labels).not.toContain("Timed Out");
    expect(labels).not.toContain("Cancelled");
    expect(labels).not.toContain("Thread Leaked");
    expect(labels).not.toContain("Suppressed");
    expect(labels).not.toContain("Dropped");
  });

  it("includes Timed Out with warn tone when timedOut > 0", () => {
    const cells = buildCommonStatCells(baseInput({ timedOut: 2 }));

    expect(cells.find((c) => c.label === "Timed Out")).toEqual({ label: "Timed Out", value: 2, tone: "warn" });
  });

  it("includes Cancelled with cancel tone when cancelled > 0", () => {
    const cells = buildCommonStatCells(baseInput({ cancelled: 1 }));

    expect(cells.find((c) => c.label === "Cancelled")).toEqual({ label: "Cancelled", value: 1, tone: "cancel" });
  });

  it("includes Thread Leaked with warn tone when threadLeaked > 0", () => {
    const cells = buildCommonStatCells(baseInput({ threadLeaked: 4 }));

    expect(cells.find((c) => c.label === "Thread Leaked")).toEqual({
      label: "Thread Leaked",
      value: 4,
      tone: "warn",
    });
  });

  it("includes Suppressed with mute tone when suppressedCount > 0", () => {
    const cells = buildCommonStatCells(baseInput({ suppressedCount: 6 }));

    expect(cells.find((c) => c.label === "Suppressed")).toEqual({ label: "Suppressed", value: 6, tone: "mute" });
  });

  it("includes Dropped with warn tone when droppedCount > 0", () => {
    const cells = buildCommonStatCells(baseInput({ droppedCount: 7 }));

    expect(cells.find((c) => c.label === "Dropped")).toEqual({ label: "Dropped", value: 7, tone: "warn" });
  });

  it("returns only the common cells — no domain-specific cells like Backpressure Dropped or Skipped", () => {
    const cells = buildCommonStatCells(baseInput());
    const labels = cells.map((c) => c.label);

    expect(labels).not.toContain("Backpressure Dropped");
    expect(labels).not.toContain("Skipped");
  });

  it("preserves conditional cell order: Timed Out, Cancelled, Thread Leaked, Suppressed, Dropped", () => {
    const cells = buildCommonStatCells(
      baseInput({ timedOut: 1, cancelled: 1, threadLeaked: 1, suppressedCount: 1, droppedCount: 1 }),
    );
    const conditionalLabels = cells.slice(5).map((c) => c.label);

    expect(conditionalLabels).toEqual(["Timed Out", "Cancelled", "Thread Leaked", "Suppressed", "Dropped"]);
  });

  describe("extraCell", () => {
    it("inserts right after Cancelled when both Timed Out and Cancelled render", () => {
      const cells = buildCommonStatCells(
        baseInput({
          timedOut: 1,
          cancelled: 1,
          extraCell: { label: "Skipped", value: 3, tone: "mute" },
        }),
      );

      expect(cells.slice(5).map((c) => c.label)).toEqual(["Timed Out", "Cancelled", "Skipped"]);
    });

    it("inserts right after Timed Out when Cancelled does not render", () => {
      const cells = buildCommonStatCells(
        baseInput({
          timedOut: 1,
          cancelled: 0,
          extraCell: { label: "Skipped", value: 3, tone: "mute" },
        }),
      );

      expect(cells.slice(5).map((c) => c.label)).toEqual(["Timed Out", "Skipped"]);
    });

    it("inserts at the start of the conditional zone when neither Timed Out nor Cancelled render", () => {
      const cells = buildCommonStatCells(
        baseInput({
          timedOut: 0,
          cancelled: 0,
          threadLeaked: 1,
          extraCell: { label: "Skipped", value: 3, tone: "mute" },
        }),
      );

      expect(cells.slice(5).map((c) => c.label)).toEqual(["Skipped", "Thread Leaked"]);
    });

    it("omits the cell entirely when not provided", () => {
      const cells = buildCommonStatCells(baseInput({ timedOut: 1, cancelled: 1 }));

      expect(cells.map((c) => c.label)).not.toContain("Skipped");
    });
  });
});
