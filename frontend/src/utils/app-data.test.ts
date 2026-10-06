import { describe, expect, it } from "vitest";

import type { AppActivity, AppStatus, ResourceStatus } from "../api/endpoints";
import type { AppStatusEntry } from "../state/store";
import { createAppActivityStats, createAppGridEntry, createAppHealth, createInstance } from "../test/factories";
import { appLiveStatus, compareAppRows, hasFailedActivityPart, toAppRow } from "./app-data";

const NO_LIVE_STATUSES: Record<string, AppStatusEntry> = {};

/** A grid row for `appKey` whose cached instances have the given statuses, indexed from 0. */
function instanceRow(appKey: string, status: AppStatus, instanceStatuses: ResourceStatus[]) {
  return toAppRow(
    createAppGridEntry({
      app: {
        app_key: appKey,
        status,
        instance_count: instanceStatuses.length,
        instances: instanceStatuses.map((s, index) => createInstance({ app_key: appKey, index, status: s })),
      },
    }),
  );
}

describe("appLiveStatus", () => {
  it("returns row.status directly for single-instance apps", () => {
    const row = toAppRow(createAppGridEntry({ app: { app_key: "solo_app", status: "running", instances: [] } }));
    expect(appLiveStatus(NO_LIVE_STATUSES, row)).toBe("running");
  });

  it("returns disabled as-is instead of letting a leftover per-instance WS status override it", () => {
    // Disabling an app tears down its instance, which emits a "stopped" WS event for that
    // index. That event lingers in the live appStatus store after the manifest becomes
    // disabled — the config state must win, not the stale per-instance status.
    const row = toAppRow(createAppGridEntry({ app: { app_key: "disabled_app", status: "disabled", instances: [] } }));
    const liveStatuses: Record<string, AppStatusEntry> = {
      "disabled_app:0": { status: "stopped", index: 0 },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("disabled");
  });

  it("returns blocked as-is instead of letting a leftover per-instance WS status override it", () => {
    const row = toAppRow(createAppGridEntry({ app: { app_key: "blocked_app", status: "blocked", instances: [] } }));
    const liveStatuses: Record<string, AppStatusEntry> = {
      "blocked_app:0": { status: "failed", index: 0 },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("blocked");
  });

  it("derives degraded from a live running+failed mix, not from cached row.status", () => {
    const row = instanceRow("multi_app", "degraded", ["running", "failed"]);
    expect(appLiveStatus(NO_LIVE_STATUSES, row)).toBe("degraded");
  });

  it("reports degraded from a live running+failed mix even when row.status is stale 'running'", () => {
    // The dashboard grid query is invalidated on execution events, not app_status_changed, so
    // row.status can lag the live WS view — a manifest that just degraded may still read
    // "running" from the cache until an unrelated execution refetches it.
    const row = instanceRow("multi_app", "running", ["running", "running"]);
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:0": { status: "running", index: 0 },
      "multi_app:1": { status: "failed", index: 1 },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("degraded");
  });

  it("clears a stale degraded row.status once live statuses show full recovery", () => {
    const row = instanceRow("multi_app", "degraded", ["running", "failed"]);
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:0": { status: "running", index: 0 },
      "multi_app:1": { status: "running", index: 1 },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("running");
  });

  it("merges a live index absent from the cached instance snapshot", () => {
    // A hot reload that expands a healthy single-instance app to two instances delivers a WS
    // update for the new index before any execution event refetches the grid, so row.instances
    // still only has index 0. The live index 1 must still be folded into the reduction.
    const row = instanceRow("multi_app", "running", ["running"]);
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:0": { status: "running", index: 0 },
      "multi_app:1": { status: "failed", index: 1 },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("degraded");
  });

  it("merges multiple live indices added beyond the cached snapshot in one reload", () => {
    // A reload can add more than one instance at once; the forward probe must keep walking
    // past the first new index rather than stopping after finding just one.
    const row = instanceRow("multi_app", "running", ["running"]);
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:0": { status: "running", index: 0 },
      "multi_app:1": { status: "running", index: 1 },
      "multi_app:2": { status: "failed", index: 2 },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("degraded");
  });

  it("still reduces per-instance statuses for multi-instance apps that are not degraded", () => {
    const row = instanceRow("multi_app", "running", ["running", "starting"]);
    // "starting" is worse (lower priority number) than "running" in STATUS_PRIORITY.
    expect(appLiveStatus(NO_LIVE_STATUSES, row)).toBe("starting");
  });
});

describe("compareAppRows status sort", () => {
  it("sorts a degraded app ahead of a running app (warn-tier, not last)", () => {
    const degraded = instanceRow("degraded_app", "degraded", ["running", "failed"]);
    const running = toAppRow(createAppGridEntry({ app: { app_key: "running_app", status: "running" } }));

    const ascending = compareAppRows(degraded, running, { key: "status", dir: "asc" }, NO_LIVE_STATUSES);
    expect(ascending).toBeLessThan(0);
  });
});

describe("compareAppRows activity sorts", () => {
  const row = (app_key: string, activity: Partial<AppActivity>) =>
    toAppRow(createAppGridEntry({ app: { app_key }, activity }));
  const busy = row("busy", { stats: createAppActivityStats({ total_invocations: 90, total_executions: 10 }) });
  const quiet = row("quiet", {
    stats: createAppActivityStats({ total_invocations: 1, total_executions: 0, health: createAppHealth() }),
  });
  const unknown = row("unknown", { stats: null });

  function sorted(key: "runs" | "last", dir: "asc" | "desc"): string[] {
    return [unknown, busy, quiet]
      .sort((a, b) => compareAppRows(a, b, { key, dir }, NO_LIVE_STATUSES))
      .map((r) => r.app_key);
  }

  it.each(["asc", "desc"] as const)("sorts a row with uncomputed stats last by runs (%s)", (dir) => {
    expect(sorted("runs", dir)[2]).toBe("unknown");
  });

  it.each(["asc", "desc"] as const)("sorts a row with uncomputed stats last by last activity (%s)", (dir) => {
    expect(sorted("last", dir)[2]).toBe("unknown");
  });

  it("orders computed rows by total runs", () => {
    expect(sorted("runs", "asc")).toEqual(["quiet", "busy", "unknown"]);
    expect(sorted("runs", "desc")).toEqual(["busy", "quiet", "unknown"]);
  });

  it("sorts a never-run app (computed stats, no activity) as zero, not as uncomputed", () => {
    const neverRan = row("never_ran", {
      stats: createAppActivityStats({ health: createAppHealth({ last_activity_ts: null }) }),
    });
    const order = [unknown, neverRan, busy]
      .sort((a, b) => compareAppRows(a, b, { key: "last", dir: "asc" }, NO_LIVE_STATUSES))
      .map((r) => r.app_key);
    expect(order).toEqual(["never_ran", "busy", "unknown"]);
  });
});

describe("hasFailedActivityPart", () => {
  const grid = (since: number | null, activity: Partial<AppActivity>) => ({
    apps: [createAppGridEntry({ activity })],
    since,
  });

  it("is false for a fully computed grid and for no data", () => {
    expect(hasFailedActivityPart(grid(1000, {}))).toBe(false);
    expect(hasFailedActivityPart(undefined)).toBe(false);
  });

  it("is true when an unwindowed part is null, with or without a window", () => {
    expect(hasFailedActivityPart(grid(null, { stats: null }))).toBe(true);
    expect(hasFailedActivityPart(grid(1000, { blocking_event_count: null }))).toBe(true);
  });

  it("treats null windowed parts as failed only when the since echo says a window was requested", () => {
    expect(hasFailedActivityPart(grid(null, { activity_buckets: null, last_error: null }))).toBe(false);
    expect(hasFailedActivityPart(grid(1000, { last_error: null }))).toBe(true);
  });
});
