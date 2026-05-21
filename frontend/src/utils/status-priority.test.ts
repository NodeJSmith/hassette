import { describe, expect, it } from "vitest";

import { STATUS_PRIORITY, statusPriority } from "./status-priority";

describe("STATUS_PRIORITY", () => {
  it("assigns lower numbers to more severe statuses", () => {
    expect(STATUS_PRIORITY["failed"]).toBeLessThan(STATUS_PRIORITY["running"]);
    expect(STATUS_PRIORITY["blocked"]).toBeLessThan(STATUS_PRIORITY["running"]);
    expect(STATUS_PRIORITY["running"]).toBeLessThan(STATUS_PRIORITY["stopped"]);
    expect(STATUS_PRIORITY["stopped"]).toBeLessThan(STATUS_PRIORITY["disabled"]);
  });

  it("treats failed, crashed, and exhausted_dead as equal severity", () => {
    expect(STATUS_PRIORITY["failed"]).toBe(STATUS_PRIORITY["crashed"]);
    expect(STATUS_PRIORITY["failed"]).toBe(STATUS_PRIORITY["exhausted_dead"]);
  });

  it("treats stopping and shutting_down as equal severity", () => {
    expect(STATUS_PRIORITY["stopping"]).toBe(STATUS_PRIORITY["shutting_down"]);
  });

  it("covers all known app statuses", () => {
    const expected = [
      "failed",
      "crashed",
      "exhausted_dead",
      "blocked",
      "exhausted_cooling",
      "starting",
      "running",
      "stopping",
      "shutting_down",
      "stopped",
      "disabled",
      "not_started",
    ];
    for (const status of expected) {
      expect(STATUS_PRIORITY).toHaveProperty(status);
    }
  });
});

describe("statusPriority", () => {
  it("returns the priority for known statuses", () => {
    expect(statusPriority("failed")).toBe(0);
    expect(statusPriority("running")).toBe(4);
    expect(statusPriority("disabled")).toBe(7);
  });

  it("returns 99 for unknown statuses", () => {
    expect(statusPriority("nonexistent")).toBe(99);
  });
});
