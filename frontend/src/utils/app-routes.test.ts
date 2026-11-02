import { describe, expect, it } from "vitest";

import {
  appDetailPath,
  executionPath,
  handlerPath,
  HOME_PATH,
  logEntryExecutionHref,
  NAV_PAGES,
  parseInstanceParam,
} from "./app-routes";

describe("NAV_PAGES", () => {
  it("contains expected top-level pages", () => {
    const labels = NAV_PAGES.map((p) => p.label);
    expect(labels).toEqual(["apps", "handlers", "logs", "config", "diagnostics"]);
  });

  it("does not include internal pages", () => {
    const paths = NAV_PAGES.map((p) => p.path);
    expect(paths).not.toContain("/design");
  });
});

describe("HOME_PATH", () => {
  it("points to apps", () => {
    expect(HOME_PATH).toBe("/apps");
  });
});

describe("appDetailPath", () => {
  it("builds app root path", () => {
    expect(appDetailPath("my_app")).toBe("/apps/my_app");
  });

  it("builds app tab path", () => {
    expect(appDetailPath("my_app", "handlers")).toBe("/apps/my_app/handlers");
  });

  it("appends query params", () => {
    expect(appDetailPath("my_app", undefined, { instance: "office" })).toBe("/apps/my_app?instance=office");
  });

  it("omits null/undefined query values", () => {
    expect(appDetailPath("my_app", "logs", { instance: null })).toBe("/apps/my_app/logs");
  });
});

describe("handlerPath", () => {
  it("builds listener path", () => {
    expect(handlerPath("my_app", "listener", 5)).toBe("/apps/my_app/handlers/listener/5");
  });

  it("builds job path", () => {
    expect(handlerPath("my_app", "job", 3)).toBe("/apps/my_app/handlers/job/3");
  });

  it("appends query params", () => {
    expect(handlerPath("my_app", "listener", 5, { instance: "office" })).toBe(
      "/apps/my_app/handlers/listener/5?instance=office",
    );
  });
});

describe("executionPath", () => {
  it("builds execution path", () => {
    expect(executionPath("my_app", "listener", 5, "exec-1")).toBe("/apps/my_app/handlers/listener/5/exec/exec-1");
  });

  it("appends instance query", () => {
    expect(executionPath("my_app", "job", 3, "exec-2", { instance: "office" })).toBe(
      "/apps/my_app/handlers/job/3/exec/exec-2?instance=office",
    );
  });
});

describe("logEntryExecutionHref", () => {
  const base = { app_key: "my_app", execution_id: "exec-1", instance_name: null };

  it("returns href for handler kind with listener_id", () => {
    expect(logEntryExecutionHref({ ...base, execution_kind: "handler", listener_id: 5, job_id: null })).toBe(
      "/apps/my_app/handlers/listener/5/exec/exec-1",
    );
  });

  it("returns href for job kind with job_id", () => {
    expect(logEntryExecutionHref({ ...base, execution_kind: "job", listener_id: null, job_id: 3 })).toBe(
      "/apps/my_app/handlers/job/3/exec/exec-1",
    );
  });

  it("returns null for handler kind with null listener_id", () => {
    expect(logEntryExecutionHref({ ...base, execution_kind: "handler", listener_id: null, job_id: 3 })).toBeNull();
  });

  it("returns null for job kind with null job_id", () => {
    expect(logEntryExecutionHref({ ...base, execution_kind: "job", listener_id: 5, job_id: null })).toBeNull();
  });

  it("returns null when execution_kind is null", () => {
    expect(logEntryExecutionHref({ ...base, execution_kind: null, listener_id: 5, job_id: 3 })).toBeNull();
  });

  it("returns null when execution_kind is undefined", () => {
    expect(logEntryExecutionHref({ ...base, listener_id: 5, job_id: 3 })).toBeNull();
  });

  it("appends instance query param when present", () => {
    expect(
      logEntryExecutionHref({
        ...base,
        execution_kind: "handler",
        listener_id: 5,
        job_id: null,
        instance_name: "office",
      }),
    ).toBe("/apps/my_app/handlers/listener/5/exec/exec-1?instance=office");
  });
});

describe("parseInstanceParam", () => {
  it("returns the name as given", () => {
    expect(parseInstanceParam("office")).toBe("office");
  });

  it("returns undefined for an absent or empty value", () => {
    expect(parseInstanceParam(null)).toBeUndefined();
    expect(parseInstanceParam("")).toBeUndefined();
    expect(parseInstanceParam("  ")).toBeUndefined();
  });

  it("does not validate the shape; membership is checked against the manifest", () => {
    expect(parseInstanceParam("0")).toBe("0");
  });
});
