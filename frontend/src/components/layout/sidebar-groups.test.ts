import { describe, expect, it } from "vitest";

import type { AppStatusEntry } from "../../state/store";
import { createInstance, createManifest } from "../../test/factories";
import { findDuplicateDisplayNames, getGroupKey, groupAndSortApps } from "./sidebar-groups";

type LiveStatuses = Record<string, AppStatusEntry>;

const NO_LIVE_STATUSES: LiveStatuses = {};

describe("getGroupKey", () => {
  it("groups a degraded manifest under the warn (SLOW) group, not healthy", () => {
    const manifest = createManifest({
      status: "degraded",
      instance_count: 2,
      instances: [createInstance({ index: 0, status: "running" }), createInstance({ index: 1, status: "failed" })],
    });
    expect(getGroupKey(manifest, NO_LIVE_STATUSES)).toBe("warn");
  });

  it("still reduces per-instance statuses for non-degraded multi-instance manifests", () => {
    const manifest = createManifest({
      status: "running",
      instance_count: 2,
      instances: [createInstance({ index: 0, status: "running" }), createInstance({ index: 1, status: "starting" })],
    });
    // "starting" is worse (lower priority number) than "running" in STATUS_PRIORITY, so the
    // group is derived from that reduced status rather than the cached manifest.status.
    expect(getGroupKey(manifest, NO_LIVE_STATUSES)).toBe("ok");
  });

  it("derives the group from live WS status, not a stale cached manifest.status", () => {
    // Regression: manifest.status can lag a since-failed instance (see getGroupKey's doc comment).
    // FAILING group membership must catch this via the live appStatus store.
    const manifest = createManifest({ app_key: "stale_running_app", status: "running", instance_count: 1 });
    const liveStatuses: LiveStatuses = {
      "stale_running_app:0": { status: "failed", index: 0 },
    };
    expect(getGroupKey(manifest, liveStatuses)).toBe("err");
  });

  it("groups a disabled app under DISABLED, not STOPPED, despite a leftover per-instance WS status", () => {
    // Disabling an app tears down its instance, emitting a "stopped" WS event for that index
    // that lingers in the live appStatus store after the manifest becomes disabled. The
    // manifest-level config state must win over that stale per-instance status.
    const manifest = createManifest({ app_key: "disabled_app", status: "disabled", instance_count: 1 });
    const liveStatuses: LiveStatuses = {
      "disabled_app:0": { status: "stopped", index: 0 },
    };
    expect(getGroupKey(manifest, liveStatuses)).toBe("disabled");
  });

  it("groups a blocked app under BLOCKED despite a leftover per-instance WS status", () => {
    const manifest = createManifest({ app_key: "blocked_app", status: "blocked", instance_count: 1 });
    const liveStatuses: LiveStatuses = {
      "blocked_app:0": { status: "failed", index: 0 },
    };
    expect(getGroupKey(manifest, liveStatuses)).toBe("blocked");
  });

  it("clears a stale cached degraded status once live per-instance statuses fully recover", () => {
    const manifest = createManifest({
      app_key: "recovered_app",
      status: "degraded",
      instance_count: 2,
      instances: [
        createInstance({ app_key: "recovered_app", index: 0, status: "running" }),
        createInstance({ app_key: "recovered_app", index: 1, status: "failed" }),
      ],
    });
    const liveStatuses: LiveStatuses = {
      "recovered_app:0": { status: "running", index: 0 },
      "recovered_app:1": { status: "running", index: 1 },
    };
    expect(getGroupKey(manifest, liveStatuses)).toBe("ok");
  });
});

describe("findDuplicateDisplayNames", () => {
  it("returns an empty set when all display names are unique", () => {
    const manifests = [
      createManifest({ app_key: "a", display_name: "Alpha" }),
      createManifest({ app_key: "b", display_name: "Beta" }),
    ];
    expect(findDuplicateDisplayNames(manifests)).toEqual(new Set());
  });

  it("returns the colliding display name when two manifests share it", () => {
    const manifests = [
      createManifest({ app_key: "blocking_io_lab", display_name: "BlockingIOLab" }),
      createManifest({ app_key: "blocking_io_lab_ignore", display_name: "BlockingIOLab" }),
    ];
    expect(findDuplicateDisplayNames(manifests)).toEqual(new Set(["BlockingIOLab"]));
  });

  it("returns an empty set for a single manifest", () => {
    expect(findDuplicateDisplayNames([createManifest()])).toEqual(new Set());
  });

  it("returns an empty set for an empty list", () => {
    expect(findDuplicateDisplayNames([])).toEqual(new Set());
  });
});

describe("groupAndSortApps", () => {
  it("threads live statuses through to each manifest's group assignment", () => {
    const manifest = createManifest({ app_key: "stale_running_app", status: "running", instance_count: 1 });
    const liveStatuses: LiveStatuses = {
      "stale_running_app:0": { status: "failed", index: 0 },
    };
    const { groups } = groupAndSortApps([manifest], liveStatuses);
    expect(groups.get("err")).toEqual([manifest]);
    expect(groups.get("ok")).toEqual([]);
  });

  it("considers the app set healthy when only running and disabled apps are present", () => {
    const running = createManifest({ app_key: "running_app", status: "running" });
    const disabled = createManifest({ app_key: "disabled_app", status: "disabled" });
    const { allHealthy } = groupAndSortApps([running, disabled], NO_LIVE_STATUSES);
    expect(allHealthy).toBe(true);
  });

  it.each([
    { status: "failed", group: "err" },
    { status: "blocked", group: "blocked" },
    { status: "degraded", group: "warn" },
    { status: "stopped", group: "stopped" },
  ] as const)("considers the app set unhealthy when the $group group is populated ($status)", ({ status }) => {
    const manifest = createManifest({ app_key: `${status}_app`, status });
    const { allHealthy } = groupAndSortApps([manifest], NO_LIVE_STATUSES);
    expect(allHealthy).toBe(false);
  });
});
