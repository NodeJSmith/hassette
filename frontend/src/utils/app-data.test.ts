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

  it("derives degraded from a live running+failed mix, not from cached row.status", () => {
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

  it("reports degraded from a live running+failed mix even when row.status is stale 'running'", () => {
    // The dashboard grid query is invalidated on execution events, not app_status_changed, so
    // row.status can lag the live WS view — a manifest that just degraded may still read
    // "running" from the cache until an unrelated execution refetches it.
    const row = toAppRow(
      createAppGridEntry({
        app_key: "multi_app",
        status: "running",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "multi_app", index: 0, status: "running" }),
          createInstance({ app_key: "multi_app", index: 1, status: "running" }),
        ],
      }),
    );
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:0": { status: "running", index: 0 },
      "multi_app:1": { status: "failed", index: 1 },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("degraded");
  });

  it("clears a stale degraded row.status once live statuses show full recovery", () => {
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
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:0": { status: "running", index: 0 },
      "multi_app:1": { status: "running", index: 1 },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("running");
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
