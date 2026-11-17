import { describe, expect, it } from "vitest";

import type { AppActivity, AppStatus, ResourceStatus } from "../api/endpoints";
import type { AppStatusEntry } from "../state/store";
import { createAppActivityStats, createAppGridEntry, createAppHealth, createInstance } from "../test/factories";
import { appLiveStatus, appNeedsRestart, compareAppRows, hasFailedActivityPart, toAppRow } from "./app-data";

const NO_LIVE_STATUSES: Record<string, AppStatusEntry> = {};

/** A grid row for `appKey` whose cached instances have the given statuses, named `inst_<position>`. */
function instanceRow(appKey: string, status: AppStatus, instanceStatuses: ResourceStatus[]) {
  return toAppRow(
    createAppGridEntry({
      app: {
        app_key: appKey,
        status,
        instance_count: instanceStatuses.length,
        instances: instanceStatuses.map((s, index) =>
          createInstance({ app_key: appKey, instance_name: `inst_${index}`, status: s }),
        ),
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
    // instance. That event lingers in the live appStatus store after the manifest becomes
    // disabled — the config state must win, not the stale per-instance status.
    const row = toAppRow(createAppGridEntry({ app: { app_key: "disabled_app", status: "disabled", instances: [] } }));
    const liveStatuses: Record<string, AppStatusEntry> = {
      "disabled_app:inst_0": { status: "stopped", instance_name: "inst_0" },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("disabled");
  });

  it("returns blocked as-is instead of letting a leftover per-instance WS status override it", () => {
    const row = toAppRow(createAppGridEntry({ app: { app_key: "blocked_app", status: "blocked", instances: [] } }));
    const liveStatuses: Record<string, AppStatusEntry> = {
      "blocked_app:inst_0": { status: "failed", instance_name: "inst_0" },
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
      "multi_app:inst_0": { status: "running", instance_name: "inst_0" },
      "multi_app:inst_1": { status: "failed", instance_name: "inst_1" },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("degraded");
  });

  it.each(["starting", "stopping", "not_started"] as const)(
    "derives degraded from a failed instance beside a %s one, as the server's rollup does",
    (sibling) => {
      const row = instanceRow("multi_app", "degraded", ["failed", "running"]);
      const liveStatuses: Record<string, AppStatusEntry> = {
        "multi_app:inst_0": { status: "failed", instance_name: "inst_0" },
        "multi_app:inst_1": { status: sibling, instance_name: "inst_1" },
      };
      expect(appLiveStatus(liveStatuses, row)).toBe("degraded");
    },
  );

  it("reports failed, not degraded, for a failed instance beside a stopped one", () => {
    const row = instanceRow("multi_app", "failed", ["failed", "stopped"]);
    expect(appLiveStatus(NO_LIVE_STATUSES, row)).toBe("failed");
  });

  it("clears a stale degraded row.status once live statuses show full recovery", () => {
    const row = instanceRow("multi_app", "degraded", ["running", "failed"]);
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:inst_0": { status: "running", instance_name: "inst_0" },
      "multi_app:inst_1": { status: "running", instance_name: "inst_1" },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("running");
  });

  it("ignores a store entry for a name the cached row does not list", () => {
    // A removed instance's last status lingers in the store; only the refetched row decides membership.
    const row = instanceRow("multi_app", "running", ["running", "running"]);
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:inst_0": { status: "running", instance_name: "inst_0" },
      "multi_app:inst_1": { status: "running", instance_name: "inst_1" },
      "multi_app:removed": { status: "failed", instance_name: "removed" },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("running");
  });

  it("does not let a stale failed entry of a removed instance degrade a single-instance row", () => {
    const row = instanceRow("multi_app", "running", ["running"]);
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:removed": { status: "failed", instance_name: "removed" },
    };
    expect(appLiveStatus(liveStatuses, row)).toBe("running");
  });

  it("does not count a just-added name until the refetched row lists it", () => {
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:inst_0": { status: "running", instance_name: "inst_0" },
      "multi_app:inst_1": { status: "failed", instance_name: "inst_1" },
    };
    const before = instanceRow("multi_app", "running", ["running"]);
    expect(appLiveStatus(liveStatuses, before)).toBe("running");

    const after = instanceRow("multi_app", "running", ["running", "running"]);
    expect(appLiveStatus(liveStatuses, after)).toBe("degraded");
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

describe("appNeedsRestart", () => {
  it("ignores a flag on a name the grid hasn't listed", () => {
    // A config reload added inst_1 after the grid loaded; it counts once the refetched row lists it.
    const row = instanceRow("multi_app", "running", ["running"]);
    const flag = { reason: "task loop still pending", pending_tasks: ["loop"], flagged_at: 1 };
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:inst_1": { status: "failed", instance_name: "inst_1", needs_restart: flag },
    };

    expect(appNeedsRestart(liveStatuses, row)).toEqual({ count: 0, flag: null });
    const refetched = instanceRow("multi_app", "running", ["running", "running"]);
    expect(appNeedsRestart(liveStatuses, refetched)).toEqual({ count: 1, flag });
  });

  it("keeps a cached flag when the instance's last WS event carried none", () => {
    // The STOPPING event arrived before the flag was set, and the FAILED event that carried it was lost.
    const flag = { reason: "task loop still pending", pending_tasks: ["loop"], flagged_at: 1 };
    const row = toAppRow(
      createAppGridEntry({
        app: {
          app_key: "multi_app",
          status: "failed",
          instance_count: 1,
          instances: [
            createInstance({ app_key: "multi_app", instance_name: "inst_0", status: "failed", needs_restart: flag }),
          ],
        },
      }),
    );
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:inst_0": { status: "stopping", instance_name: "inst_0", needs_restart: null },
    };

    expect(appNeedsRestart(liveStatuses, row)).toEqual({ count: 1, flag });
  });

  it("counts flags that come from the cached row and a WS event on different instances", () => {
    const cachedFlag = { reason: "task loop still pending", pending_tasks: ["loop"], flagged_at: 1 };
    const liveFlag = { reason: "task poll still pending", pending_tasks: ["poll"], flagged_at: 2 };
    const row = toAppRow(
      createAppGridEntry({
        app: {
          app_key: "multi_app",
          status: "failed",
          instance_count: 2,
          instances: [
            createInstance({
              app_key: "multi_app",
              instance_name: "inst_0",
              status: "failed",
              needs_restart: cachedFlag,
            }),
            createInstance({ app_key: "multi_app", instance_name: "inst_1", status: "running" }),
          ],
        },
      }),
    );
    const liveStatuses: Record<string, AppStatusEntry> = {
      "multi_app:inst_1": { status: "failed", instance_name: "inst_1", needs_restart: liveFlag },
    };

    expect(appNeedsRestart(liveStatuses, row)).toEqual({ count: 2, flag: null });
  });
});
