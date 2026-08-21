// dup-ignore-start: shared import prologue also present in use-telemetry-health.test.ts and
// use-websocket.test.ts (T04/T02); import statements can't be extracted into a shared helper
import { act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAppStore } from "../state/store";
import { useFakeTimersForEachTest, waitForCallCount } from "../test/query-test-utils";
import { expectFetchSince, renderAndWaitForFirstFetch, renderScopedQuery } from "../test/scoped-query-test-utils";
// dup-ignore-end

const BASE_TIME_S = 1_700_000_000;

describe("useScopedQuery", () => {
  useFakeTimersForEachTest();

  beforeEach(() => {
    vi.setSystemTime(BASE_TIME_S * 1000);
  });

  it("blocks fetches until uptimeSeconds is available for since-restart preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    // dup-ignore-start: this render+advance-timers+assert-call-count sequence is a genuinely
    // distinct scenario (asserts the fetch is still BLOCKED) from the near-identical-looking
    // "no refetch after this timer advance" sequences later in this file (uptime-not-in-key,
    // urlWindowParam-override) — coincidental token-shape overlap, not unresolved boilerplate.
    const { result } = renderScopedQuery("test-key", fetcher, { storeOverrides: { timePreset: "since-restart" } });

    // Advance time — should still not fetch
    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(fetcher).toHaveBeenCalledTimes(0);
    // dup-ignore-end
    expect(result.current.isPending).toBe(true);
  });

  it("fetches once uptimeSeconds becomes available", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    renderScopedQuery("test-fetch-on-uptime", fetcher, { storeOverrides: { timePreset: "since-restart" } });

    // Still blocked
    expect(fetcher).toHaveBeenCalledTimes(0);

    // uptimeSeconds arrives
    act(() => {
      useAppStore.setState({ uptimeSeconds: 120 });
    });

    await waitForCallCount(fetcher, 1);
  });

  it("computes since = now - uptimeSeconds for since-restart preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    renderScopedQuery("test-since-restart", fetcher, { storeOverrides: { timePreset: "since-restart" } });

    const expectedSince = BASE_TIME_S - 300;
    act(() => {
      useAppStore.setState({ uptimeSeconds: 300 });
    });

    await waitForCallCount(fetcher, 1);

    expect(fetcher).toHaveBeenCalledWith(expectedSince, expect.any(AbortSignal));
  });

  it("computes since = now - 3600 for 1h preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    renderScopedQuery("test-1h", fetcher, { storeOverrides: { timePreset: "1h", uptimeSeconds: 7200 } });

    await expectFetchSince(fetcher, BASE_TIME_S - 3600);
  });

  it("computes since = now - 86400 for 24h preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    renderScopedQuery("test-24h", fetcher, { storeOverrides: { timePreset: "24h", uptimeSeconds: null } });

    await expectFetchSince(fetcher, BASE_TIME_S - 86400);
  });

  it("computes since = now - 604800 for 7d preset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    renderScopedQuery("test-7d", fetcher, { storeOverrides: { timePreset: "7d", uptimeSeconds: null } });

    await expectFetchSince(fetcher, BASE_TIME_S - 604800);
  });

  it("respects effectiveTimePreset — urlWindowParam overrides timePreset", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    renderScopedQuery("test-url-override", fetcher, {
      storeOverrides: { timePreset: "1h", urlWindowParam: "7d", uptimeSeconds: 7200 },
    });

    // Should use 7d (urlWindowParam), not 1h (timePreset)
    await expectFetchSince(fetcher, BASE_TIME_S - 604800);
  });

  it("refetches when preset changes (different query key)", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    await renderAndWaitForFirstFetch("test-preset-change", fetcher, {
      storeOverrides: { timePreset: "1h", uptimeSeconds: 7200 },
    });

    act(() => {
      useAppStore.setState({ timePreset: "24h" });
    });

    await waitForCallCount(fetcher, 2);

    // Second call should use 24h window; use toBeCloseTo for floating-point tolerance
    const lastCallArg = fetcher.mock.calls[1][0] as number;
    expect(lastCallArg).toBeCloseTo(BASE_TIME_S - 86400, 0);
  });

  it("refetches when uptimeSeconds changes for since-restart preset (uptime is in key)", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    await renderAndWaitForFirstFetch("test-uptime-in-key", fetcher, {
      storeOverrides: { timePreset: "since-restart", uptimeSeconds: 300 },
    });

    act(() => {
      useAppStore.setState({ uptimeSeconds: 5 });
    });

    await waitForCallCount(fetcher, 2);

    // since = now - 5; use toBeCloseTo for floating-point tolerance
    const lastCallArg = fetcher.mock.calls[1][0] as number;
    expect(lastCallArg).toBeCloseTo(BASE_TIME_S - 5, 0);
  });

  it("does NOT refetch when uptimeSeconds changes for fixed-window presets (uptime not in key)", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    await renderAndWaitForFirstFetch("test-uptime-not-in-key", fetcher, {
      storeOverrides: { timePreset: "1h", uptimeSeconds: 100 },
    });

    // uptimeSeconds changes — should NOT cause a refetch for fixed-window preset
    // dup-ignore-start: this advance-timers+assert-call-count sequence is a genuinely distinct
    // scenario (no refetch after an uptimeSeconds change on a fixed-window preset) from the
    // near-identical-looking "still blocked" and "no refetch after urlWindowParam override" checks
    // elsewhere in this file — coincidental token-shape overlap, not unresolved boilerplate.
    act(() => {
      useAppStore.setState({ uptimeSeconds: 9999 });
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });

    // Still just the one fetch
    expect(fetcher).toHaveBeenCalledTimes(1);
    // dup-ignore-end
  });

  it("fetches immediately with since=0 when waitForUptime is false and uptime is unavailable", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    // uptimeSeconds defaults to null

    const { result } = renderScopedQuery("test-no-wait", fetcher, {
      storeOverrides: { timePreset: "since-restart" },
      hookOptions: { waitForUptime: false },
    });

    await waitForCallCount(fetcher, 1);

    expect(fetcher).toHaveBeenCalledWith(0, expect.any(AbortSignal));

    await vi.waitFor(() => {
      expect(result.current.isPending).toBe(false);
    });
  });

  it("refetches with the accurate window once uptime arrives when waitForUptime is false", async () => {
    const fetcher = vi.fn<(since: number, signal: AbortSignal) => Promise<string>>().mockResolvedValue("data");

    await renderAndWaitForFirstFetch("test-no-wait-refetch", fetcher, {
      storeOverrides: { timePreset: "since-restart" },
      hookOptions: { waitForUptime: false },
    });
    expect(fetcher).toHaveBeenCalledWith(0, expect.any(AbortSignal));

    act(() => {
      useAppStore.setState({ uptimeSeconds: 300 });
    });

    await waitForCallCount(fetcher, 2);

    const lastCallArg = fetcher.mock.calls[1][0];
    expect(lastCallArg).toBeCloseTo(BASE_TIME_S - 300, 0);
  });

  it("does not refetch when timePreset changes while urlWindowParam is overriding", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");

    await renderAndWaitForFirstFetch("test-no-refetch-when-overriding", fetcher, {
      storeOverrides: { timePreset: "1h", urlWindowParam: "7d", uptimeSeconds: 7200 },
    });

    // Changing timePreset while urlWindowParam is active should not refetch
    // because effectiveTimePreset (urlWindowParam = "7d") hasn't changed
    // dup-ignore-start: this advance-timers+assert-call-count sequence is a genuinely distinct
    // scenario (no refetch after a timePreset change while urlWindowParam overrides it) from the
    // near-identical-looking "still blocked" and "no refetch after uptimeSeconds change" checks
    // elsewhere in this file — coincidental token-shape overlap, not unresolved boilerplate.
    act(() => {
      useAppStore.setState({ timePreset: "24h" });
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
    // dup-ignore-end
  });
});
