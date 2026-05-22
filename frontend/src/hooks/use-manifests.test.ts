/**
 * Tests for useManifests hook.
 *
 * Uses vi.fn() mocks for getManifests (matching the established pattern for
 * renderHook tests in this codebase) and renderHookWithProviders to ensure
 * the hook runs inside QueryClientProvider + AppStateContext.
 */
import { describe, expect, it, vi } from "vitest";

import * as endpoints from "../api/endpoints";
import type { components } from "../api/generated-types";
import { createManifest } from "../test/factories";
import { createTestQueryClient, renderHookWithProviders } from "../test/query-test-utils";
import { useManifests } from "./use-manifests";

type ManifestListResponse = components["schemas"]["AppManifestListResponse"];

function makeManifestResponse(overrides: Partial<ManifestListResponse> = {}): ManifestListResponse {
  return {
    total: 0,
    running: 0,
    failed: 0,
    stopped: 0,
    disabled: 0,
    blocked: 0,
    manifests: [],
    only_app: null,
    ...overrides,
  };
}

describe("useManifests", () => {
  it("returns AppManifest[] unwrapped from ManifestListResponse.manifests", async () => {
    const manifests = [
      createManifest({ app_key: "app_a", display_name: "App A" }),
      createManifest({ app_key: "app_b", display_name: "App B" }),
    ];
    vi.spyOn(endpoints, "getManifests").mockResolvedValue(makeManifestResponse({ total: 2, running: 2, manifests }));

    const { result } = renderHookWithProviders(() => useManifests());

    // Before resolution: data is undefined
    expect(result.current.data).toBeUndefined();

    // Wait for query to resolve
    await vi.waitFor(() => {
      expect(result.current.data).toBeDefined();
    });

    expect(result.current.data).toHaveLength(2);
    expect(result.current.data![0].app_key).toBe("app_a");
    expect(result.current.data![1].app_key).toBe("app_b");
    // Verify wrapper fields are NOT returned (select unwraps)
    expect((result.current.data as unknown as { total?: number }).total).toBeUndefined();
  });

  it("data is undefined when query is pending (no data yet)", () => {
    // Create a promise that never resolves to keep the query in pending state
    vi.spyOn(endpoints, "getManifests").mockReturnValue(new Promise(() => {}));

    const { result } = renderHookWithProviders(() => useManifests());

    // Before any async resolution: data is undefined, isPending is true
    expect(result.current.data).toBeUndefined();
    expect(result.current.isPending).toBe(true);
  });

  it("multiple components calling useManifests share one network request (deduplication)", async () => {
    let callCount = 0;
    vi.spyOn(endpoints, "getManifests").mockImplementation(() => {
      callCount++;
      return Promise.resolve(
        makeManifestResponse({
          total: 1,
          running: 1,
          manifests: [createManifest({ app_key: "shared_app" })],
        }),
      );
    });

    // Share the same QueryClient so both hooks deduplicate into one request
    const queryClient = createTestQueryClient();
    const { result: result1 } = renderHookWithProviders(() => useManifests(), { queryClient });
    const { result: result2 } = renderHookWithProviders(() => useManifests(), { queryClient });

    // Wait for both hooks to resolve
    await vi.waitFor(() => {
      expect(result1.current.data).toBeDefined();
    });

    // Both hooks see the same resolved data
    expect(result1.current.data).toHaveLength(1);
    expect(result2.current.data).toHaveLength(1);
    // Deduplication: two hooks on the same queryClient → one network request
    expect(callCount).toBe(1);
  });
});
