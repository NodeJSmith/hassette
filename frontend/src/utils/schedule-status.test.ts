import { describe, expect, it } from "vitest";

import { scheduleStatusDisplay } from "./schedule-status";

describe("scheduleStatusDisplay", () => {
  it("returns manual display info", () => {
    expect(scheduleStatusDisplay("manual")).toEqual({ label: "manual", text: "Manual only." });
  });

  it("returns waiting display info", () => {
    expect(scheduleStatusDisplay("waiting")).toEqual({ label: "waiting", text: "Waiting for entity time." });
  });

  it("returns completed display info with no reason", () => {
    expect(scheduleStatusDisplay("completed")).toEqual({ label: "completed", text: "Schedule completed." });
  });

  it("returns completed/trigger_error override with the same label as the default", () => {
    expect(scheduleStatusDisplay("completed", "trigger_error")).toEqual({
      label: "completed",
      text: "Schedule stopped after trigger error.",
    });
  });

  it("returns scheduled/legacy_unknown override", () => {
    expect(scheduleStatusDisplay("scheduled", "legacy_unknown")).toEqual({
      label: "unknown",
      text: "Legacy status unknown.",
    });
  });

  it("returns null for scheduled with no reason (caller resolves via next_run timing)", () => {
    expect(scheduleStatusDisplay("scheduled", null)).toBeNull();
    expect(scheduleStatusDisplay("scheduled")).toBeNull();
  });

  it("returns null for scheduled with an unrecognized reason", () => {
    expect(scheduleStatusDisplay("scheduled", "some_other_reason")).toBeNull();
  });

  it("ignores reason overrides for statuses that don't define one", () => {
    expect(scheduleStatusDisplay("manual", "some_reason")).toEqual({ label: "manual", text: "Manual only." });
    expect(scheduleStatusDisplay("waiting", "some_reason")).toEqual({
      label: "waiting",
      text: "Waiting for entity time.",
    });
  });

  it("returns null for a null status", () => {
    expect(scheduleStatusDisplay(null)).toBeNull();
  });

  it("returns null for an unrecognized status", () => {
    expect(scheduleStatusDisplay("exploding")).toBeNull();
  });
});
