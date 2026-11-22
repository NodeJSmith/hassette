import { describe, expect, it } from "vitest";

import type { AppActivity, AppStatus, ResourceStatus } from "../api/endpoints";
import type { AppStatusEntry, LiveAppStatus } from "../state/store";
import { createAppActivityStats, createAppGridEntry, createAppHealth, createInstance } from "../test/factories";
import {
  appLiveStatus,
  appNeedsRestart,
  compareAppRows,
  hasFailedActivityPart,
  instanceLiveError,
  instanceLiveNeedsRestart,
  instanceLiveStatus,
  toAppRow,
} from "./app-data";

const NO_LIVE_STATUSES: LiveAppStatus = { instances: {}, apps: {} };
/** The `status_revision` every test row is read at. */
const ROW_REVISION = 100;

/** A grid row for `appKey` whose cached instances have the given statuses, named `inst_<position>`. */
function instanceRow(appKey: string, status: AppStatus, instanceStatuses: ResourceStatus[]) {
  return toAppRow(
    createAppGridEntry({
      app: {
        app_key: appKey,
        status,
        status_revision: ROW_REVISION,
        instance_count: instanceStatuses.length,
        instances: instanceStatuses.map((s, index) =>
          createInstance({ app_key: appKey, instance_name: `inst_${index}`, status: s }),
        ),
      },
    }),
  );
}

/** A store holding one instance delta (and the app rollup it carried) at `revision`. */
function liveDelta(
  appKey: string,
  entry: Omit<AppStatusEntry, "status_revision">,
  appStatus: AppStatus,
  revision: number,
): LiveAppStatus {
  return {
    instances: { [`${appKey}:${entry.instance_name}`]: { ...entry, status_revision: revision } },
    apps: { [appKey]: { app_status: appStatus, status_revision: revision } },
  };
}

describe("appLiveStatus", () => {
  it("returns the row's server rollup when no delta has arrived", () => {
    const row = instanceRow("multi_app", "starting", ["running", "starting"]);
    expect(appLiveStatus(NO_LIVE_STATUSES, row)).toBe("starting");
  });

  it("applies a delta's app_status only when strictly newer than the row", () => {
    const row = instanceRow("app", "running", ["running"]);
    const failing = (revision: number) =>
      liveDelta("app", { instance_name: "inst_0", status: "failed" }, "failed", revision);

    expect(appLiveStatus(failing(ROW_REVISION + 1), row)).toBe("failed");
    // A tie goes to the snapshot, and an older delta never overrides it.
    expect(appLiveStatus(failing(ROW_REVISION), row)).toBe("running");
    expect(appLiveStatus(failing(ROW_REVISION - 1), row)).toBe("running");
  });

  it("lets a refetched disabled row win over the delta that preceded the disable", () => {
    // Disabling sends no delta; it bumps the revision and reaches the row through apps_changed.
    const live = liveDelta("app", { instance_name: "inst_0", status: "running" }, "running", ROW_REVISION - 5);
    expect(appLiveStatus(live, instanceRow("app", "disabled", []))).toBe("disabled");
  });

  it("does not derive a rollup from instance deltas", () => {
    const live: LiveAppStatus = {
      instances: { "app:inst_1": { instance_name: "inst_1", status: "failed", status_revision: ROW_REVISION + 1 } },
      apps: {},
    };
    expect(appLiveStatus(live, instanceRow("app", "running", ["running", "running"]))).toBe("running");
  });
});

describe("instance live helpers", () => {
  const row = instanceRow("app", "failed", ["failed"]);
  const inst = { ...row.instances[0], error_message: "boom" };

  it("apply a newer delta, including its null exception", () => {
    const live = liveDelta("app", { instance_name: "inst_0", status: "running", exception: null }, "running", 101);
    expect(instanceLiveStatus(live, row, inst)).toBe("running");
    expect(instanceLiveError(live, row, inst)).toBeNull();
  });

  it("keep the snapshot instance on a tie", () => {
    const live = liveDelta("app", { instance_name: "inst_0", status: "running", exception: null }, "running", 100);
    expect(instanceLiveStatus(live, row, inst)).toBe("failed");
    expect(instanceLiveError(live, row, inst)).toBe("boom");
  });

  it("clear a cached needs-restart flag only through a newer delta", () => {
    const flag = { reason: "task loop still pending", pending_tasks: ["loop"], flagged_at: 1 };
    const flagged = { ...inst, needs_restart: flag };
    const older = liveDelta(
      "app",
      { instance_name: "inst_0", status: "stopping", needs_restart: null },
      "stopping",
      99,
    );
    expect(instanceLiveNeedsRestart(older, row, flagged)).toEqual(flag);
    const newer = liveDelta("app", { instance_name: "inst_0", status: "running", needs_restart: null }, "running", 101);
    expect(instanceLiveNeedsRestart(newer, row, flagged)).toBeNull();
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
  const flag = { reason: "task loop still pending", pending_tasks: ["loop"], flagged_at: 1 };

  it("ignores a flag on a name the grid hasn't listed", () => {
    // A config reload added inst_1 after the grid loaded; it counts once the refetched row lists it.
    const row = instanceRow("multi_app", "running", ["running"]);
    const live = liveDelta(
      "multi_app",
      { instance_name: "inst_1", status: "failed", needs_restart: flag },
      "failed",
      101,
    );

    expect(appNeedsRestart(live, row)).toEqual({ count: 0, flag: null });
    const refetched = instanceRow("multi_app", "running", ["running", "running"]);
    expect(appNeedsRestart(live, refetched)).toEqual({ count: 1, flag });
  });

  it("counts flags that come from the cached row and a newer delta on different instances", () => {
    const liveFlag = { reason: "task poll still pending", pending_tasks: ["poll"], flagged_at: 2 };
    const row = toAppRow(
      createAppGridEntry({
        app: {
          app_key: "multi_app",
          status: "failed",
          status_revision: ROW_REVISION,
          instance_count: 2,
          instances: [
            createInstance({ app_key: "multi_app", instance_name: "inst_0", status: "failed", needs_restart: flag }),
            createInstance({ app_key: "multi_app", instance_name: "inst_1", status: "running" }),
          ],
        },
      }),
    );
    const live = liveDelta(
      "multi_app",
      { instance_name: "inst_1", status: "failed", needs_restart: liveFlag },
      "failed",
      101,
    );

    expect(appNeedsRestart(live, row)).toEqual({ count: 2, flag: null });
  });
});
