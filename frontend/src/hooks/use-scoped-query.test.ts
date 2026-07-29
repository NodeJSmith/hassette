import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAppStore } from "../state/store";
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

    const { result } = renderHookWithProviders(() => useScopedQuery(["test-key"], fetcher), {
      storeOverrides: { timePreset: "since-restart" },
    });

    // Advance time — should still not fetch
    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(fetcher).toHaveBeenCalledTimes(0);
    expect(result.current.isPending).toBe(true);
  });

  it("fetches once uptimeSeconds becomes available", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-fetch-on-uptime"], fetcher), {
      storeOverrides: { timePreset: "since-restart" },
      queryClient,
    });

    // Still blocked
    expect(fetcher).toHaveBeenCalledTimes(0);

    // uptimeSeconds arrives
    act(() => {
      useAppStore.setState({ uptimeSeconds: 120 });
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });
  });

  it("computes since = now - uptimeSeconds for since-restart preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-since-restart"], fetcher), {
      storeOverrides: { timePreset: "since-restart" },
      queryClient,
    });

    const expectedSince = BASE_TIME_S - 300;
    act(() => {
      useAppStore.setState({ uptimeSeconds: 300 });
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    expect(fetcher).toHaveBeenCalledWith(expectedSince, expect.any(AbortSignal));
  });

  it("computes since = now - 3600 for 1h preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    renderHookWithProviders(() => useScopedQuery(["test-1h"], fetcher), {
      storeOverrides: { timePreset: "1h", uptimeSeconds: 7200 },
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(BASE_TIME_S - 3600, expect.any(AbortSignal));
  });

  it("computes since = now - 86400 for 24h preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    renderHookWithProviders(() => useScopedQuery(["test-24h"], fetcher), {
      storeOverrides: { timePreset: "24h", uptimeSeconds: null },
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(BASE_TIME_S - 86400, expect.any(AbortSignal));
  });

  it("computes since = now - 604800 for 7d preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    renderHookWithProviders(() => useScopedQuery(["test-7d"], fetcher), {
      storeOverrides: { timePreset: "7d", uptimeSeconds: null },
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(BASE_TIME_S - 604800, expect.any(AbortSignal));
  });

  it("respects effectiveTimePreset — urlWindowParam overrides timePreset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    renderHookWithProviders(() => useScopedQuery(["test-url-override"], fetcher), {
      storeOverrides: { timePreset: "1h", urlWindowParam: "7d", uptimeSeconds: 7200 },
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    // Should use 7d (urlWindowParam), not 1h (timePreset)
    expect(fetcher).toHaveBeenCalledWith(BASE_TIME_S - 604800, expect.any(AbortSignal));
  });

  it("refetches when preset changes (different query key)", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-preset-change"], fetcher), {
      storeOverrides: { timePreset: "1h", uptimeSeconds: 7200 },
      queryClient,
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    act(() => {
      useAppStore.setState({ timePreset: "24h" });
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
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-uptime-in-key"], fetcher), {
      storeOverrides: { timePreset: "since-restart", uptimeSeconds: 300 },
      queryClient,
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    act(() => {
      useAppStore.setState({ uptimeSeconds: 5 });
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
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-uptime-not-in-key"], fetcher), {
      storeOverrides: { timePreset: "1h", uptimeSeconds: 100 },
      queryClient,
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    // uptimeSeconds changes — should NOT cause a refetch for fixed-window preset
    act(() => {
      useAppStore.setState({ uptimeSeconds: 9999 });
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });

    // Still just the one fetch
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("fetches immediately with since=0 when waitForUptime is false and uptime is unavailable", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    // uptimeSeconds defaults to null

    const { result } = renderHookWithProviders(
      () => useScopedQuery(["test-no-wait"], fetcher, { waitForUptime: false }),
      { storeOverrides: { timePreset: "since-restart" } },
    );

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    expect(fetcher).toHaveBeenCalledWith(0, expect.any(AbortSignal));

    await vi.waitFor(() => {
      expect(result.current.isPending).toBe(false);
    });
  });

  it("refetches with the accurate window once uptime arrives when waitForUptime is false", async () => {
    const fetcher = vi.fn<(since: number, signal: AbortSignal) => Promise<string>>().mockResolvedValue("data");
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-no-wait-refetch"], fetcher, { waitForUptime: false }), {
      storeOverrides: { timePreset: "since-restart" },
      queryClient,
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });
    expect(fetcher).toHaveBeenCalledWith(0, expect.any(AbortSignal));

    act(() => {
      useAppStore.setState({ uptimeSeconds: 300 });
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    const lastCallArg = fetcher.mock.calls[1][0];
    expect(lastCallArg).toBeCloseTo(BASE_TIME_S - 300, 0);
  });

  it("does not refetch when timePreset changes while urlWindowParam is overriding", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useScopedQuery(["test-no-refetch-when-overriding"], fetcher), {
      storeOverrides: { timePreset: "1h", urlWindowParam: "7d", uptimeSeconds: 7200 },
      queryClient,
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    // Changing timePreset while urlWindowParam is active should not refetch
    // because effectiveTimePreset (urlWindowParam = "7d") hasn't changed
    act(() => {
      useAppStore.setState({ timePreset: "24h" });
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
