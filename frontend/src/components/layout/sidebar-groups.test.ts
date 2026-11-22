import { describe, expect, it } from "vitest";

import type { AppStatus } from "../../api/endpoints";
import type { LiveAppStatus } from "../../state/store";
import { createAppSummary, createInstance } from "../../test/factories";
import { findDuplicateDisplayNames, getGroupKey, groupAndSortApps } from "./sidebar-groups";

const NO_LIVE_STATUSES: LiveAppStatus = { instances: {}, apps: {} };

/** An app rollup delta at `revision` (the default row's `status_revision` is 100). */
function liveRollup(appKey: string, status: AppStatus, revision: number): LiveAppStatus {
  return { instances: {}, apps: { [appKey]: { app_status: status, status_revision: revision } } };
}

describe("getGroupKey", () => {
  it("groups a degraded manifest under the warn (WARNING) group, not healthy", () => {
    const manifest = createAppSummary({
      status: "degraded",
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "failed" }),
      ],
    });
    expect(getGroupKey(manifest, NO_LIVE_STATUSES)).toBe("warn");
  });

  it("uses the row's server rollup, not a reduction of its instance statuses", () => {
    const manifest = createAppSummary({
      status: "running",
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "starting" }),
      ],
    });
    expect(getGroupKey(manifest, NO_LIVE_STATUSES)).toBe("ok");
  });

  it("derives the group from a newer live rollup, not a stale cached manifest.status", () => {
    const manifest = createAppSummary({ app_key: "stale_running_app", status: "running" });
    expect(getGroupKey(manifest, liveRollup("stale_running_app", "failed", 101))).toBe("err");
  });

  it("keeps the manifest's group when the live rollup is not strictly newer", () => {
    const manifest = createAppSummary({ app_key: "app", status: "running" });
    expect(getGroupKey(manifest, liveRollup("app", "failed", 100))).toBe("ok");
    expect(getGroupKey(manifest, liveRollup("app", "failed", 99))).toBe("ok");
  });

  it("groups a refetched disabled app under DISABLED despite an older delta", () => {
    const manifest = createAppSummary({ app_key: "disabled_app", status: "disabled", instance_count: 1 });
    expect(getGroupKey(manifest, liveRollup("disabled_app", "stopped", 95))).toBe("disabled");
  });

  it("groups a refetched blocked app under BLOCKED despite an older delta", () => {
    const manifest = createAppSummary({ app_key: "blocked_app", status: "blocked", instance_count: 1 });
    expect(getGroupKey(manifest, liveRollup("blocked_app", "failed", 95))).toBe("blocked");
  });

  it("clears a stale cached degraded status once a newer rollup reports recovery", () => {
    const manifest = createAppSummary({ app_key: "recovered_app", status: "degraded" });
    expect(getGroupKey(manifest, liveRollup("recovered_app", "running", 101))).toBe("ok");
  });
});

describe("findDuplicateDisplayNames", () => {
  it("returns an empty set when all display names are unique", () => {
    const manifests = [
      createAppSummary({ app_key: "a", display_name: "Alpha" }),
      createAppSummary({ app_key: "b", display_name: "Beta" }),
    ];
    expect(findDuplicateDisplayNames(manifests)).toEqual(new Set());
  });

  it("returns the colliding display name when two manifests share it", () => {
    const manifests = [
      createAppSummary({ app_key: "blocking_io_lab", display_name: "BlockingIOLab" }),
      createAppSummary({ app_key: "blocking_io_lab_ignore", display_name: "BlockingIOLab" }),
    ];
    expect(findDuplicateDisplayNames(manifests)).toEqual(new Set(["BlockingIOLab"]));
  });

  it("returns an empty set for a single manifest", () => {
    expect(findDuplicateDisplayNames([createAppSummary()])).toEqual(new Set());
  });

  it("returns an empty set for an empty list", () => {
    expect(findDuplicateDisplayNames([])).toEqual(new Set());
  });
});

describe("groupAndSortApps", () => {
  it("threads live statuses through to each manifest's group assignment", () => {
    const manifest = createAppSummary({
      app_key: "stale_running_app",
      status: "running",
      instance_count: 1,
      instances: [createInstance({ app_key: "stale_running_app", instance_name: "inst_0", status: "running" })],
    });
    const liveStatuses = liveRollup("stale_running_app", "failed", 101);
    const { groups } = groupAndSortApps([manifest], liveStatuses);
    expect(groups.get("err")).toEqual([manifest]);
    expect(groups.get("ok")).toEqual([]);
  });

  it("considers the app set healthy when only running, stopped, and disabled apps are present", () => {
    const running = createAppSummary({ app_key: "running_app", status: "running" });
    const stopped = createAppSummary({ app_key: "stopped_app", status: "stopped" });
    const disabled = createAppSummary({ app_key: "disabled_app", status: "disabled" });
    const { allHealthy } = groupAndSortApps([running, stopped, disabled], NO_LIVE_STATUSES);
    expect(allHealthy).toBe(true);
  });

  it.each([
    { status: "failed", group: "err" },
    { status: "blocked", group: "blocked" },
    { status: "degraded", group: "warn" },
  ] as const)("considers the app set unhealthy when the $group group is populated ($status)", ({ status }) => {
    const manifest = createAppSummary({ app_key: `${status}_app`, status });
    const { allHealthy } = groupAndSortApps([manifest], NO_LIVE_STATUSES);
    expect(allHealthy).toBe(false);
  });
});
