import { describe, expect, it } from "vitest";

import type { AppStatusEntry } from "../state/store";
import { createAppGridEntry, createInstance } from "../test/factories";
import { appLiveStatus, compareAppRows, toAppRow } from "./app-data";

const NO_LIVE_STATUSES: Record<string, AppStatusEntry> = {};

describe("appLiveStatus", () => {
  it("returns row.status directly for single-instance apps", () => {
    const row = toAppRow(createAppGridEntry({ app_key: "solo_app", status: "running", instances: [] }));
    expect(appLiveStatus(NO_LIVE_STATUSES, row)).toBe("running");
  });

  it("prefers the manifest-level degraded status over the per-instance reduce for multi-instance apps", () => {
    // A degraded manifest always has a mix of running/failed instances (FR#5) — the per-instance
    // ResourceStatus values ("running", "failed") never spell "degraded" themselves, so the
    // rollup status has to come from row.status, not from reducing over instance statuses.
    const row = toAppRow(
      createAppGridEntry({
        app_key: "multi_app",
        status: "degraded",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "multi_app", index: 0, status: "running" }),
          createInstance({ app_key: "multi_app", index: 1, status: "failed" }),
        ],
      }),
    );
    expect(appLiveStatus(NO_LIVE_STATUSES, row)).toBe("degraded");
  });

  it("still reduces per-instance statuses for multi-instance apps that are not degraded", () => {
    const row = toAppRow(
      createAppGridEntry({
        app_key: "multi_app",
        status: "running",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "multi_app", index: 0, status: "running" }),
          createInstance({ app_key: "multi_app", index: 1, status: "starting" }),
        ],
      }),
    );
    // "starting" is worse (lower priority number) than "running" in STATUS_PRIORITY.
    expect(appLiveStatus(NO_LIVE_STATUSES, row)).toBe("starting");
  });
});

describe("compareAppRows status sort", () => {
  it("sorts a degraded app ahead of a running app (warn-tier, not last)", () => {
    const degraded = toAppRow(
      createAppGridEntry({
        app_key: "degraded_app",
        status: "degraded",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "degraded_app", index: 0, status: "running" }),
          createInstance({ app_key: "degraded_app", index: 1, status: "failed" }),
        ],
      }),
    );
    const running = toAppRow(createAppGridEntry({ app_key: "running_app", status: "running" }));

    const ascending = compareAppRows(degraded, running, { key: "status", dir: "asc" }, NO_LIVE_STATUSES);
    expect(ascending).toBeLessThan(0);
  });
});
