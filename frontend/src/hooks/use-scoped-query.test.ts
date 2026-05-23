import { act } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppState } from "../state/create-app-state";
import { createTestQueryClient, renderHookWithProviders } from "../test/query-test-utils";
import { useScopedQuery } from "./use-scoped-query";

const BASE_TIME_S = 1_700_000_000;

describe("useScopedQuery", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE_TIME_S * 1000);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("blocks fetches until uptimeSeconds is available for since-restart preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "since-restart";
    // uptimeSeconds starts as null

    const { result } = renderHookWithProviders(() => useScopedQuery(["test-key"], fetcher), { stateOverrides: state });

    // Advance time — should still not fetch
    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(fetcher).toHaveBeenCalledTimes(0);
    expect(result.current.isPending).toBe(true);
  });

  it("fetches once uptimeSeconds becomes available", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "since-restart";
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-fetch-on-uptime"], fetcher), {
      stateOverrides: state,
      queryClient,
    });

    // Still blocked
    expect(fetcher).toHaveBeenCalledTimes(0);

    // uptimeSeconds arrives
    act(() => {
      state.uptimeSeconds.value = 120;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });
  });

  it("computes since = now - uptimeSeconds for since-restart preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "since-restart";
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-since-restart"], fetcher), {
      stateOverrides: state,
      queryClient,
    });

    const expectedSince = BASE_TIME_S - 300;
    act(() => {
      state.uptimeSeconds.value = 300;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    expect(fetcher).toHaveBeenCalledWith(expectedSince, expect.any(AbortSignal));
  });

  it("computes since = now - 3600 for 1h preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "1h";
    state.uptimeSeconds.value = 7200;

    renderHookWithProviders(() => useScopedQuery(["test-1h"], fetcher), { stateOverrides: state });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(BASE_TIME_S - 3600, expect.any(AbortSignal));
  });

  it("computes since = now - 86400 for 24h preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "24h";
    state.uptimeSeconds.value = null;

    renderHookWithProviders(() => useScopedQuery(["test-24h"], fetcher), { stateOverrides: state });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(BASE_TIME_S - 86400, expect.any(AbortSignal));
  });

  it("computes since = now - 604800 for 7d preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "7d";
    state.uptimeSeconds.value = null;

    renderHookWithProviders(() => useScopedQuery(["test-7d"], fetcher), { stateOverrides: state });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(BASE_TIME_S - 604800, expect.any(AbortSignal));
  });

  it("respects effectiveTimePreset — urlWindowParam overrides timePreset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "1h";
    state.urlWindowParam.value = "7d";
    state.uptimeSeconds.value = 7200;

    renderHookWithProviders(() => useScopedQuery(["test-url-override"], fetcher), { stateOverrides: state });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    // Should use 7d (urlWindowParam), not 1h (timePreset)
    expect(fetcher).toHaveBeenCalledWith(BASE_TIME_S - 604800, expect.any(AbortSignal));
  });

  it("refetches when preset changes (different query key)", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "1h";
    state.uptimeSeconds.value = 7200;
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-preset-change"], fetcher), {
      stateOverrides: state,
      queryClient,
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    act(() => {
      state.timePreset.value = "24h";
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    // Second call should use 24h window; use toBeCloseTo for floating-point tolerance
    const lastCallArg = fetcher.mock.calls[1][0] as number;
    expect(lastCallArg).toBeCloseTo(BASE_TIME_S - 86400, 0);
  });

  it("refetches when uptimeSeconds changes for since-restart preset (uptime is in key)", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "since-restart";
    state.uptimeSeconds.value = 300;
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-uptime-in-key"], fetcher), {
      stateOverrides: state,
      queryClient,
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    act(() => {
      state.uptimeSeconds.value = 5;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    // since = now - 5; use toBeCloseTo for floating-point tolerance
    const lastCallArg = fetcher.mock.calls[1][0] as number;
    expect(lastCallArg).toBeCloseTo(BASE_TIME_S - 5, 0);
  });

  it("does NOT refetch when uptimeSeconds changes for fixed-window presets (uptime not in key)", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "1h";
    state.uptimeSeconds.value = 100;
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-uptime-not-in-key"], fetcher), {
      stateOverrides: state,
      queryClient,
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    // uptimeSeconds changes — should NOT cause a refetch for fixed-window preset
    act(() => {
      state.uptimeSeconds.value = 9999;
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });

    // Still just the one fetch
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not refetch when timePreset changes while urlWindowParam is overriding", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const state = createAppState();
    state.timePreset.value = "1h";
    state.urlWindowParam.value = "7d";
    state.uptimeSeconds.value = 7200;
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-no-refetch-when-overriding"], fetcher), {
      stateOverrides: state,
      queryClient,
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    // Changing timePreset while urlWindowParam is active should not refetch
    // because effectiveTimePreset (urlWindowParam = "7d") hasn't changed
    act(() => {
      state.timePreset.value = "24h";
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
