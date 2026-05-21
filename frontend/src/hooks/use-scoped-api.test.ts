import { act, renderHook } from "@testing-library/preact";
import type { ComponentChildren } from "preact";
import { h } from "preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppStateContext } from "../state/context";
import { type AppState, createAppState } from "../state/create-app-state";
import { useScopedApi } from "./use-scoped-api";

function createWrapper(state: AppState) {
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return h(AppStateContext.Provider, { value: state }, children);
  };
}

/** Get current epoch seconds at the current fake-timer position. */
function nowSeconds(): number {
  return Date.now() / 1000;
}

describe("useScopedApi", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2025-01-01T00:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("blocks fetches until uptimeSeconds is available", async () => {
    const state = createAppState();
    // uptimeSeconds starts null — hook must not fetch

    const fetcher = vi.fn().mockResolvedValue("should-not-reach");

    const { result } = renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    // Advance time a bit — should still not fetch
    act(() => {
      vi.advanceTimersByTime(50);
    });

    expect(fetcher).toHaveBeenCalledTimes(0);
    expect(result.current.loading.value).toBe(true);
    expect(result.current.data.value).toBeNull();
  });

  it("fetches once uptimeSeconds becomes available", async () => {
    const state = createAppState();

    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    // Still blocked
    act(() => {
      vi.advanceTimersByTime(10);
    });
    expect(fetcher).toHaveBeenCalledTimes(0);

    // uptimeSeconds arrives
    act(() => {
      state.uptimeSeconds.value = 120;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });
  });

  it("computes since=now-uptimeSeconds for since-restart preset", async () => {
    const state = createAppState();
    state.timePreset.value = "since-restart";

    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    // Capture expected since at the same moment the hook will compute it
    const expectedSince = nowSeconds() - 300;
    act(() => {
      state.uptimeSeconds.value = 300;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    expect(fetcher).toHaveBeenCalledWith(expectedSince);
  });

  it("computes since=now-3600 for 1h preset", async () => {
    const state = createAppState();
    state.timePreset.value = "1h";
    state.uptimeSeconds.value = 7200;

    const fetcher = vi.fn().mockResolvedValue("data");
    const expectedSince = nowSeconds() - 3600;

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(expectedSince);
  });

  it("computes since=now-86400 for 24h preset", async () => {
    const state = createAppState();
    state.timePreset.value = "24h";
    state.uptimeSeconds.value = 100000;

    const fetcher = vi.fn().mockResolvedValue("data");
    const expectedSince = nowSeconds() - 86400;

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(expectedSince);
  });

  it("computes since=now-604800 for 7d preset", async () => {
    const state = createAppState();
    state.timePreset.value = "7d";
    state.uptimeSeconds.value = 800000;

    const fetcher = vi.fn().mockResolvedValue("data");
    const expectedSince = nowSeconds() - 604800;

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(expectedSince);
  });

  it("never passes session_id to the fetcher", async () => {
    const state = createAppState();
    state.timePreset.value = "since-restart";

    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    act(() => {
      state.uptimeSeconds.value = 120;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    // Argument must be a number (since timestamp), never an integer session_id-like value
    // being passed as the second arg or an object with session_id
    const arg = fetcher.mock.calls[0][0];
    expect(typeof arg).toBe("number");
    expect(fetcher.mock.calls[0]).toHaveLength(1);
  });

  it("refetches when timePreset changes", async () => {
    const state = createAppState();
    state.timePreset.value = "1h";
    state.uptimeSeconds.value = 7200;

    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    // Capture expected since at the moment of the preset change
    const expectedSince = nowSeconds() - 86400;
    act(() => {
      state.timePreset.value = "24h";
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    expect(fetcher).toHaveBeenLastCalledWith(expectedSince);
  });

  it("refetches when uptimeSeconds changes (reconnect)", async () => {
    const state = createAppState();
    state.timePreset.value = "since-restart";
    state.uptimeSeconds.value = 300;

    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    // Capture expected since at the moment of the uptime change
    const expectedSince = nowSeconds() - 5;
    // Server restarts — uptime_seconds resets
    act(() => {
      state.uptimeSeconds.value = 5;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    expect(fetcher).toHaveBeenLastCalledWith(expectedSince);
  });

  it("does not fetch on reconnect while uptimeSeconds is null", async () => {
    const state = createAppState();
    // uptimeSeconds starts null

    const fetcher = vi.fn().mockResolvedValue("should-not-reach");

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(fetcher).toHaveBeenCalledTimes(0);

    // Simulate reconnect version bump while still waiting
    act(() => {
      state.reconnectVersion.value = 1;
    });

    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(fetcher).toHaveBeenCalledTimes(0);
  });

  it("signal references are stable across waiting→available transition", async () => {
    const state = createAppState();

    const fetcher = vi.fn().mockResolvedValue("scoped-data");

    const { result } = renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    act(() => {
      vi.advanceTimersByTime(10);
    });

    const dataRef = result.current.data;
    const loadingRef = result.current.loading;
    const errorRef = result.current.error;

    expect(loadingRef.value).toBe(true);
    expect(dataRef.value).toBeNull();

    // uptimeSeconds arrives
    act(() => {
      state.uptimeSeconds.value = 120;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    // Same signal object references — components subscribed to these still see updates
    expect(result.current.data).toBe(dataRef);
    expect(result.current.loading).toBe(loadingRef);
    expect(result.current.error).toBe(errorRef);

    expect(result.current.data.value).toBe("scoped-data");
    expect(result.current.loading.value).toBe(false);
  });

  it("uses effectiveTimePreset (urlWindowParam overrides timePreset)", async () => {
    const state = createAppState();
    state.timePreset.value = "1h";
    state.urlWindowParam.value = "7d";
    state.uptimeSeconds.value = 7200;

    const fetcher = vi.fn().mockResolvedValue("data");
    const expectedSince = nowSeconds() - 604800; // 7d window

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(expectedSince);
  });

  it("falls back to timePreset when urlWindowParam is null", async () => {
    const state = createAppState();
    state.timePreset.value = "24h";
    state.urlWindowParam.value = null;
    state.uptimeSeconds.value = 7200;

    const fetcher = vi.fn().mockResolvedValue("data");
    const expectedSince = nowSeconds() - 86400; // 24h window

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    expect(fetcher).toHaveBeenCalledWith(expectedSince);
  });

  it("refetches when urlWindowParam changes (URL override)", async () => {
    const state = createAppState();
    state.timePreset.value = "1h";
    state.urlWindowParam.value = null;
    state.uptimeSeconds.value = 7200;

    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    const expectedSince = nowSeconds() - 604800;
    act(() => {
      state.urlWindowParam.value = "7d";
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    expect(fetcher).toHaveBeenLastCalledWith(expectedSince);
  });

  it("does not refetch when timePreset changes while urlWindowParam is overriding", async () => {
    const state = createAppState();
    state.timePreset.value = "1h";
    state.urlWindowParam.value = "7d";
    state.uptimeSeconds.value = 7200;

    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    act(() => {
      state.timePreset.value = "24h";
    });

    act(() => {
      vi.advanceTimersByTime(50);
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("preserves lazy mode", async () => {
    const state = createAppState();
    state.uptimeSeconds.value = 120;
    state.timePreset.value = "since-restart";

    const fetcher = vi.fn().mockResolvedValue("lazy-data");

    const { result } = renderHook(() => useScopedApi(fetcher, { lazy: true }), { wrapper: createWrapper(state) });

    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(fetcher).toHaveBeenCalledTimes(0);

    // Manual refetch should work
    await act(async () => {
      await result.current.refetch();
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
    const arg = fetcher.mock.calls[0][0];
    expect(typeof arg).toBe("number");
    expect(result.current.data.value).toBe("lazy-data");
  });

  it("returns no-op refetch when waiting for uptimeSeconds", async () => {
    const state = createAppState();
    // uptimeSeconds null

    const fetcher = vi.fn().mockResolvedValue("should-not-reach");

    const { result } = renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    act(() => {
      vi.advanceTimersByTime(50);
    });

    // Calling refetch while waiting should be a no-op
    await act(async () => {
      await result.current.refetch();
    });

    expect(fetcher).toHaveBeenCalledTimes(0);
  });
});
