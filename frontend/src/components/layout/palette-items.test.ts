import { describe, expect, it, vi } from "vitest";

import * as endpoints from "../../api/endpoints";
import type { AppStatusEntry } from "../../state/store";
import { createInstance, createManifest } from "../../test/factories";
import { buildActionItems, buildAppItems } from "./palette-items";

const NO_LIVE_STATUSES: Record<string, AppStatusEntry> = {};

describe("buildAppItems", () => {
  it("includes apps that are in the current config", () => {
    const items = buildAppItems(
      [createManifest({ app_key: "live_app", display_name: "Live App", in_current_config: true })],
      NO_LIVE_STATUSES,
      vi.fn(),
      vi.fn(),
    );
    expect(items.map((i) => i.id)).toContain("app-live_app");
  });

  it("excludes removed (in_current_config: false) apps", () => {
    const items = buildAppItems(
      [createManifest({ app_key: "removed_app", display_name: "Removed App", in_current_config: false })],
      NO_LIVE_STATUSES,
      vi.fn(),
      vi.fn(),
    );
    expect(items.map((i) => i.id)).not.toContain("app-removed_app");
  });

  it("also excludes instances belonging to a removed app", () => {
    const items = buildAppItems(
      [
        createManifest({
          app_key: "removed_app",
          display_name: "Removed App",
          in_current_config: false,
          instance_count: 2,
        }),
      ],
      NO_LIVE_STATUSES,
      vi.fn(),
      vi.fn(),
    );
    expect(items.some((i) => i.kind === "instance")).toBe(false);
  });

  it("shows live WS status over a stale cached manifest status for the app row", () => {
    const items = buildAppItems(
      [createManifest({ app_key: "stale_running_app", status: "running", in_current_config: true })],
      { "stale_running_app:0": { status: "failed", index: 0 } },
      vi.fn(),
      vi.fn(),
    );
    expect(items.find((i) => i.id === "app-stale_running_app")?.status).toBe("failed");
  });

  it("shows live WS status over a stale cached instance status for instance rows", () => {
    const items = buildAppItems(
      [
        createManifest({
          app_key: "multi_app",
          status: "running",
          in_current_config: true,
          instance_count: 2,
          instances: [
            createInstance({ app_key: "multi_app", index: 0, status: "running" }),
            createInstance({ app_key: "multi_app", index: 1, status: "running" }),
          ],
        }),
      ],
      { "multi_app:1": { status: "failed", index: 1 } },
      vi.fn(),
      vi.fn(),
    );
    expect(items.find((i) => i.id === "instance-multi_app-1")?.status).toBe("failed");
    expect(items.find((i) => i.id === "instance-multi_app-0")?.status).toBe("running");
  });
});

describe("buildActionItems", () => {
  it("includes degraded apps in reload-all, alongside running apps", () => {
    vi.spyOn(endpoints, "reloadApp").mockResolvedValue(undefined as never);
    const manifests = [
      createManifest({ app_key: "running_app", status: "running", in_current_config: true }),
      createManifest({ app_key: "degraded_app", status: "degraded", in_current_config: true }),
      createManifest({ app_key: "stopped_app", status: "stopped", in_current_config: true }),
    ];
    const items = buildActionItems(manifests, NO_LIVE_STATUSES, vi.fn());

    items.find((i) => i.id === "action-reload-all")?.action();

    expect(endpoints.reloadApp).toHaveBeenCalledWith("running_app");
    expect(endpoints.reloadApp).toHaveBeenCalledWith("degraded_app");
    expect(endpoints.reloadApp).not.toHaveBeenCalledWith("stopped_app");
  });

  it("includes degraded apps in stop-failing, alongside failed apps", () => {
    vi.spyOn(endpoints, "stopApp").mockResolvedValue(undefined as never);
    const manifests = [
      createManifest({ app_key: "failed_app", status: "failed", in_current_config: true }),
      createManifest({ app_key: "degraded_app", status: "degraded", in_current_config: true }),
      createManifest({ app_key: "running_app", status: "running", in_current_config: true }),
    ];
    const items = buildActionItems(manifests, NO_LIVE_STATUSES, vi.fn());

    items.find((i) => i.id === "action-stop-failing")?.action();

    expect(endpoints.stopApp).toHaveBeenCalledWith("failed_app");
    expect(endpoints.stopApp).toHaveBeenCalledWith("degraded_app");
    expect(endpoints.stopApp).not.toHaveBeenCalledWith("running_app");
  });

  it("uses live WS status over a stale cached manifest for stop-failing", () => {
    // The manifests query isn't invalidated by app_status_changed, so a manifest fetched while
    // an app was healthy can still read status: "running" after an instance has since failed.
    // The bulk command must catch this via the live appStatus store, not the cached manifest.
    vi.spyOn(endpoints, "stopApp").mockResolvedValue(undefined as never);
    const manifests = [createManifest({ app_key: "stale_running_app", status: "running", in_current_config: true })];
    const liveStatuses: Record<string, AppStatusEntry> = {
      "stale_running_app:0": { status: "failed", index: 0 },
    };
    const items = buildActionItems(manifests, liveStatuses, vi.fn());

    items.find((i) => i.id === "action-stop-failing")?.action();

    expect(endpoints.stopApp).toHaveBeenCalledWith("stale_running_app");
  });

  it("excludes a stale cached 'failed' manifest from stop-failing once live status recovers", () => {
    vi.spyOn(endpoints, "stopApp").mockResolvedValue(undefined as never);
    const manifests = [createManifest({ app_key: "recovered_app", status: "failed", in_current_config: true })];
    const liveStatuses: Record<string, AppStatusEntry> = {
      "recovered_app:0": { status: "running", index: 0 },
    };
    const items = buildActionItems(manifests, liveStatuses, vi.fn());

    items.find((i) => i.id === "action-stop-failing")?.action();

    expect(endpoints.stopApp).not.toHaveBeenCalledWith("recovered_app");
  });
});
