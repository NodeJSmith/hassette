import { describe, expect, it, vi } from "vitest";

import * as endpoints from "../../api/endpoints";
import { createManifest } from "../../test/factories";
import { buildActionItems, buildAppItems } from "./palette-items";

describe("buildAppItems", () => {
  it("includes apps that are in the current config", () => {
    const items = buildAppItems(
      [createManifest({ app_key: "live_app", display_name: "Live App", in_current_config: true })],
      vi.fn(),
      vi.fn(),
    );
    expect(items.map((i) => i.id)).toContain("app-live_app");
  });

  it("excludes removed (in_current_config: false) apps", () => {
    const items = buildAppItems(
      [createManifest({ app_key: "removed_app", display_name: "Removed App", in_current_config: false })],
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
      vi.fn(),
      vi.fn(),
    );
    expect(items.some((i) => i.kind === "instance")).toBe(false);
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
    const items = buildActionItems(manifests, vi.fn());

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
    const items = buildActionItems(manifests, vi.fn());

    items.find((i) => i.id === "action-stop-failing")?.action();

    expect(endpoints.stopApp).toHaveBeenCalledWith("failed_app");
    expect(endpoints.stopApp).toHaveBeenCalledWith("degraded_app");
    expect(endpoints.stopApp).not.toHaveBeenCalledWith("running_app");
  });
});
