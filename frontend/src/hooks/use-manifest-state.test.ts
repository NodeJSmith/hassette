import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/preact";
import type { AppManifest } from "../api/endpoints";

// Mock localStorage utilities
vi.mock("../utils/local-storage", () => ({
  getStoredSet: vi.fn().mockReturnValue(new Set<string>()),
  setStoredSet: vi.fn(),
}));

const localStorage = await import("../utils/local-storage");
const getStoredSet = localStorage.getStoredSet as ReturnType<typeof vi.fn>;
const setStoredSet = localStorage.setStoredSet as ReturnType<typeof vi.fn>;

function createManifest(appKey: string): AppManifest {
  return {
    app_key: appKey,
    class_name: "TestApp",
    display_name: "Test App",
    filename: "test.py",
    enabled: true,
    auto_loaded: true,
    status: "running",
    block_reason: null,
    instance_count: 1,
    instances: [],
    error_message: null,
    error_traceback: null,
  };
}

describe("useManifestState", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getStoredSet.mockReturnValue(new Set<string>());
  });

  it("initializes expanded from localStorage", async () => {
    getStoredSet.mockReturnValue(new Set(["app_a"]));

    const { useManifestState } = await import("./use-manifest-state");
    const { result } = renderHook(() =>
      useManifestState([createManifest("app_a")]),
    );

    expect(result.current.expanded.value).toEqual(new Set(["app_a"]));
  });

  it("toggleExpand adds a key", async () => {
    const { useManifestState } = await import("./use-manifest-state");
    const { result } = renderHook(() =>
      useManifestState([createManifest("app_a")]),
    );

    act(() => {
      result.current.toggleExpand("app_a");
    });

    expect(result.current.expanded.value.has("app_a")).toBe(true);
  });

  it("toggleExpand removes a key that is already expanded", async () => {
    getStoredSet.mockReturnValue(new Set(["app_a"]));

    const { useManifestState } = await import("./use-manifest-state");
    const { result } = renderHook(() =>
      useManifestState([createManifest("app_a")]),
    );

    act(() => {
      result.current.toggleExpand("app_a");
    });

    expect(result.current.expanded.value.has("app_a")).toBe(false);
  });

  it("prunes stale keys not present in manifests", async () => {
    getStoredSet.mockReturnValue(new Set(["stale_app", "valid_app"]));

    const { useManifestState } = await import("./use-manifest-state");
    const { result } = renderHook(() =>
      useManifestState([createManifest("valid_app")]),
    );

    expect(result.current.expanded.value.has("valid_app")).toBe(true);
    expect(result.current.expanded.value.has("stale_app")).toBe(false);
  });

  it("syncs to localStorage on state change", async () => {
    const { useManifestState, EXPANDED_KEY } = await import(
      "./use-manifest-state"
    );
    const { result } = renderHook(() =>
      useManifestState([createManifest("app_a")]),
    );

    act(() => {
      result.current.toggleExpand("app_a");
    });

    expect(setStoredSet).toHaveBeenCalledWith(
      EXPANDED_KEY,
      new Set(["app_a"]),
    );
  });
});
