import { describe, expect, it } from "vitest";

import { createInstance, createManifest } from "../../test/factories";
import { getGroupKey, worstStatus } from "./sidebar-groups";

describe("worstStatus", () => {
  it("returns degraded as-is instead of letting a failed instance mask it", () => {
    // A degraded manifest.status always coexists with at least one failed instance (that's
    // what makes it degraded) — the plain priority reduce would otherwise always pick
    // "failed" (priority 0) over "degraded" (priority 2), hiding the partial-failure state.
    const manifest = createManifest({
      status: "degraded",
      instance_count: 2,
      instances: [createInstance({ index: 0, status: "running" }), createInstance({ index: 1, status: "failed" })],
    });
    expect(worstStatus(manifest)).toBe("degraded");
  });

  it("still reduces per-instance statuses for non-degraded multi-instance manifests", () => {
    const manifest = createManifest({
      status: "running",
      instance_count: 2,
      instances: [createInstance({ index: 0, status: "running" }), createInstance({ index: 1, status: "starting" })],
    });
    expect(worstStatus(manifest)).toBe("starting");
  });
});

describe("getGroupKey", () => {
  it("groups a degraded manifest under the warn (SLOW) group, not healthy", () => {
    const manifest = createManifest({
      status: "degraded",
      instance_count: 2,
      instances: [createInstance({ index: 0, status: "running" }), createInstance({ index: 1, status: "failed" })],
    });
    expect(getGroupKey(manifest)).toBe("warn");
  });
});
