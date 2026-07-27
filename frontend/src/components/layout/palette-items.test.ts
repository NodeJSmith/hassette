import { describe, expect, it, vi } from "vitest";

import { createManifest } from "../../test/factories";
import { buildAppItems } from "./palette-items";

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
