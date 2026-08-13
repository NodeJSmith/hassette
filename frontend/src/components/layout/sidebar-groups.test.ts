import { describe, expect, it } from "vitest";

import type { AppStatusEntry } from "../../state/store";
import { createInstance, createManifest } from "../../test/factories";
import { getGroupKey, groupAndSortApps } from "./sidebar-groups";

const NO_LIVE_STATUSES: Record<string, AppStatusEntry> = {};

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
    // The sidebar's manifests query isn't invalidated by app_status_changed, so a manifest
    // fetched while an app was healthy can still read status: "running" after an instance has
    // since failed. The FAILING group membership must catch this via the live appStatus store.
    const manifest = createManifest({ app_key: "stale_running_app", status: "running", instance_count: 1 });
    const liveStatuses: Record<string, AppStatusEntry> = {
      "stale_running_app:0": { status: "failed", index: 0 },
    };
    expect(getGroupKey(manifest, liveStatuses)).toBe("err");
  });

  it("groups a disabled app under DISABLED, not STOPPED, despite a leftover per-instance WS status", () => {
    // Disabling an app tears down its instance, emitting a "stopped" WS event for that index
    // that lingers in the live appStatus store after the manifest becomes disabled. The
    // manifest-level config state must win over that stale per-instance status.
    const manifest = createManifest({ app_key: "disabled_app", status: "disabled", instance_count: 1 });
    const liveStatuses: Record<string, AppStatusEntry> = {
      "disabled_app:0": { status: "stopped", index: 0 },
    };
    expect(getGroupKey(manifest, liveStatuses)).toBe("disabled");
  });

  it("groups a blocked app under BLOCKED despite a leftover per-instance WS status", () => {
    const manifest = createManifest({ app_key: "blocked_app", status: "blocked", instance_count: 1 });
    const liveStatuses: Record<string, AppStatusEntry> = {
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
    const liveStatuses: Record<string, AppStatusEntry> = {
      "recovered_app:0": { status: "running", index: 0 },
      "recovered_app:1": { status: "running", index: 1 },
    };
    expect(getGroupKey(manifest, liveStatuses)).toBe("ok");
  });
});

describe("groupAndSortApps", () => {
  it("threads live statuses through to each manifest's group assignment", () => {
    const manifest = createManifest({ app_key: "stale_running_app", status: "running", instance_count: 1 });
    const liveStatuses: Record<string, AppStatusEntry> = {
      "stale_running_app:0": { status: "failed", index: 0 },
    };
    const { groups } = groupAndSortApps([manifest], liveStatuses);
    expect(groups.get("err")).toEqual([manifest]);
    expect(groups.get("ok")).toEqual([]);
  });
});
