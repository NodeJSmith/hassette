import { describe, expect, it } from "vitest";
import { isFrameworkKey, frameworkDisplayName, frameworkDisplayLabel } from "./framework-keys";

describe("isFrameworkKey", () => {
  it("test_isFrameworkKey_prefixed: matches __hassette__.<component> keys", () => {
    expect(isFrameworkKey("__hassette__.service_watcher")).toBe(true);
    expect(isFrameworkKey("__hassette__.app_handler")).toBe(true);
    expect(isFrameworkKey("__hassette__.core")).toBe(true);
  });

  it("test_isFrameworkKey_bare: matches the bare __hassette__ key", () => {
    expect(isFrameworkKey("__hassette__")).toBe(true);
  });

  it("test_isFrameworkKey_null: returns false for null and undefined", () => {
    expect(isFrameworkKey(null)).toBe(false);
    expect(isFrameworkKey(undefined)).toBe(false);
  });

  it("test_isFrameworkKey_app: returns false for regular app keys", () => {
    expect(isFrameworkKey("my_app")).toBe(false);
    expect(isFrameworkKey("climate_control")).toBe(false);
    expect(isFrameworkKey("")).toBe(false);
  });

  it("does not match keys that merely start with __hassette without the prefix", () => {
    expect(isFrameworkKey("__hassette_fake")).toBe(false);
  });
});

describe("frameworkDisplayName", () => {
  it("test_frameworkDisplayName: extracts component slug from prefixed key", () => {
    expect(frameworkDisplayName("__hassette__.service_watcher")).toBe("service_watcher");
    expect(frameworkDisplayName("__hassette__.app_handler")).toBe("app_handler");
    expect(frameworkDisplayName("__hassette__.core")).toBe("core");
  });

  it("returns 'framework' for bare key", () => {
    expect(frameworkDisplayName("__hassette__")).toBe("framework");
  });
});

describe("frameworkDisplayLabel", () => {
  it("test_frameworkDisplayLabel: title-cases component slug", () => {
    expect(frameworkDisplayLabel("__hassette__.service_watcher")).toBe("Service Watcher");
    expect(frameworkDisplayLabel("__hassette__.app_handler")).toBe("App Handler");
    expect(frameworkDisplayLabel("__hassette__.core")).toBe("Core");
  });

  it("handles CamelCase component names", () => {
    expect(frameworkDisplayLabel("__hassette__.ServiceWatcher")).toBe("Service Watcher");
    expect(frameworkDisplayLabel("__hassette__.AppHandler")).toBe("App Handler");
    expect(frameworkDisplayLabel("__hassette__.SessionManager")).toBe("Session Manager");
  });

  it("title-cases bare key to 'Framework'", () => {
    expect(frameworkDisplayLabel("__hassette__")).toBe("Framework");
  });
});
