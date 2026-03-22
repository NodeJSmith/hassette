import { describe, expect, it, vi } from "vitest";
import { renderHook, act } from "@testing-library/preact";
import { h } from "preact";
import type { ComponentChildren } from "preact";
import { useApi } from "./use-api";
import { AppStateContext } from "../state/context";
import { createAppState, type AppState } from "../state/create-app-state";

function createWrapper(state: AppState) {
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return h(AppStateContext.Provider, { value: state }, children);
  };
}

describe("useApi reconnect awareness", () => {
  it("refetches when reconnectVersion increments", async () => {
    const state = createAppState();
    const fetcher = vi.fn().mockResolvedValue("data");

    const { result } = renderHook(() => useApi(fetcher), {
      wrapper: createWrapper(state),
    });

    // Wait for initial fetch
    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });
    expect(result.current.data.value).toBe("data");

    // Simulate reconnect
    act(() => {
      state.reconnectVersion.value = 1;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });
  });

  it("does not refetch when reconnectVersion stays at 0", async () => {
    const state = createAppState();
    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    // Force a re-render without changing reconnectVersion
    act(() => {
      state.connection.value = "connected";
    });

    // Small delay to ensure no extra fetch fires
    await new Promise((r) => setTimeout(r, 50));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not double-fetch when mounted after reconnect already occurred", async () => {
    const state = createAppState();
    // Simulate a reconnect that already happened before mount
    state.reconnectVersion.value = 3;

    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    // Wait to ensure no reconnect-triggered refetch fires
    await new Promise((r) => setTimeout(r, 50));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe("useApi lazy mode", () => {
  it("does not fetch on mount when lazy is true", async () => {
    const state = createAppState();
    const fetcher = vi.fn().mockResolvedValue("lazy-data");

    const { result } = renderHook(() => useApi(fetcher, [], { lazy: true }), {
      wrapper: createWrapper(state),
    });

    // Wait a tick to ensure any async effects have settled
    await new Promise((r) => setTimeout(r, 50));

    // Fetcher should NOT have been called
    expect(fetcher).toHaveBeenCalledTimes(0);

    // Initial state should be loading=false, data=null
    expect(result.current.loading.value).toBe(false);
    expect(result.current.data.value).toBeNull();

    // Manual refetch should work
    await act(async () => {
      await result.current.refetch();
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current.data.value).toBe("lazy-data");
    expect(result.current.loading.value).toBe(false);
  });

  it("reconnect refetch works for lazy instances after first manual fetch", async () => {
    const state = createAppState();
    const fetcher = vi.fn().mockResolvedValue("lazy-data");

    const { result } = renderHook(() => useApi(fetcher, [], { lazy: true }), {
      wrapper: createWrapper(state),
    });

    // Wait to confirm no initial fetch
    await new Promise((r) => setTimeout(r, 50));
    expect(fetcher).toHaveBeenCalledTimes(0);

    // Manual refetch
    await act(async () => {
      await result.current.refetch();
    });
    expect(fetcher).toHaveBeenCalledTimes(1);

    // Simulate reconnect
    act(() => {
      state.reconnectVersion.value = 1;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });
  });

  it("does not clear data on refetch (stale-while-revalidate)", async () => {
    const state = createAppState();
    let callCount = 0;
    const fetcher = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          callCount++;
          // Second call takes longer to verify stale data stays visible
          const delay = callCount === 1 ? 0 : 100;
          setTimeout(() => resolve(`data-${callCount}`), delay);
        }),
    );

    const { result } = renderHook(() => useApi(fetcher, [], { lazy: true }), {
      wrapper: createWrapper(state),
    });

    // First fetch
    await act(async () => {
      await result.current.refetch();
    });
    expect(result.current.data.value).toBe("data-1");

    // Start second fetch — data should NOT be cleared
    act(() => {
      void result.current.refetch();
    });

    // While loading, stale data should remain
    expect(result.current.loading.value).toBe(true);
    expect(result.current.data.value).toBe("data-1");

    // Wait for second fetch to complete
    await vi.waitFor(() => {
      expect(result.current.data.value).toBe("data-2");
    });
  });
});
