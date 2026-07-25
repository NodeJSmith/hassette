import { describe, expect, it } from "vitest";

import { buildTrail, type HandlerNameResolver } from "./breadcrumb-trail";

const noName: HandlerNameResolver = () => undefined;
const named: HandlerNameResolver = () => "on_kitchen_light";

describe("buildTrail — top-level routes", () => {
  it("returns a single unlinked crumb for a nav page", () => {
    expect(buildTrail("/logs", undefined, noName)).toEqual([{ label: "logs" }]);
  });

  it("returns a single unlinked crumb for the apps index", () => {
    expect(buildTrail("/apps", undefined, noName)).toEqual([{ label: "apps" }]);
  });

  it("returns nothing for an unknown route", () => {
    expect(buildTrail("/nope", undefined, noName)).toEqual([]);
  });

  it("returns nothing for the root path", () => {
    expect(buildTrail("/", undefined, noName)).toEqual([]);
  });
});

describe("buildTrail — app routes", () => {
  it("links ancestors and leaves the current page unlinked", () => {
    expect(buildTrail("/apps/demo_app", undefined, noName)).toEqual([
      { label: "apps", href: "/apps" },
      { label: "demo_app" },
    ]);
  });

  it("includes the tab as a crumb", () => {
    expect(buildTrail("/apps/demo_app/handlers", undefined, noName)).toEqual([
      { label: "apps", href: "/apps" },
      { label: "demo_app", href: "/apps/demo_app" },
      { label: "handlers" },
    ]);
  });

  it("ignores a path segment that is not a known tab", () => {
    expect(buildTrail("/apps/demo_app/bogus", undefined, noName)).toEqual([
      { label: "apps", href: "/apps" },
      { label: "demo_app" },
    ]);
  });
});

describe("buildTrail — handler and execution routes", () => {
  it("uses the resolved handler name when the cache has it", () => {
    const trail = buildTrail("/apps/demo_app/handlers/listener/42", undefined, named);
    expect(trail[trail.length - 1]).toEqual({ label: "on_kitchen_light" });
  });

  it("falls back to the id when the cache is cold", () => {
    const trail = buildTrail("/apps/demo_app/handlers/listener/42", undefined, noName);
    expect(trail[trail.length - 1]).toEqual({ label: "listener 42" });
  });

  it("extends the trail with a truncated execution id", () => {
    const trail = buildTrail("/apps/demo_app/handlers/job/7/exec/abc123def456", undefined, named);
    expect(trail.map((c) => c.label)).toEqual(["apps", "demo_app", "handlers", "on_kitchen_light", "…23def456"]);
    expect(trail[trail.length - 1].href).toBeUndefined();
  });

  it("keeps the handler crumb linked once an execution is selected", () => {
    const trail = buildTrail("/apps/demo_app/handlers/listener/42/exec/abc123def456", undefined, named);
    expect(trail[3].href).toBe("/apps/demo_app/handlers/listener/42");
  });

  it("stops at the tab when the handler kind is unrecognized", () => {
    const trail = buildTrail("/apps/demo_app/handlers/bogus/42", undefined, named);
    expect(trail.map((c) => c.label)).toEqual(["apps", "demo_app", "handlers"]);
  });

  it("does not ask the resolver for a non-numeric id", () => {
    const trail = buildTrail("/apps/demo_app/handlers/listener/abc", undefined, named);
    expect(trail[trail.length - 1]).toEqual({ label: "listener abc" });
  });
});

describe("buildTrail — instance scoping", () => {
  it("carries the instance index onto ancestor links", () => {
    const trail = buildTrail("/apps/demo_app/handlers/listener/42", 2, named);
    expect(trail[1].href).toBe("/apps/demo_app?instance=2");
    expect(trail[2].href).toBe("/apps/demo_app/handlers?instance=2");
  });

  it("omits the query when no instance is active", () => {
    const trail = buildTrail("/apps/demo_app/handlers", undefined, named);
    expect(trail[1].href).toBe("/apps/demo_app");
  });
});
