import { describe, expect, it, vi } from "vitest";
import { renderHook, act } from "@testing-library/preact";
import { h } from "preact";
import type { ComponentChildren } from "preact";
import { useScopedApi } from "./use-scoped-api";
import { AppStateContext } from "../state/context";
import { createAppState, type AppState } from "../state/create-app-state";

function createWrapper(state: AppState) {
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return h(AppStateContext.Provider, { value: state }, children);
  };
}

describe("useScopedApi", () => {
  it("resolves sessionId for current scope", async () => {
    const state = createAppState();
    state.sessionId.value = 5;
    state.sessionScope.value = "current";

    const fetcher = vi.fn().mockResolvedValue("scoped-data");

    const { result } = renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    expect(fetcher).toHaveBeenCalledWith(5);
    expect(result.current.data.value).toBe("scoped-data");
  });

  it("resolves null for all scope", async () => {
    const state = createAppState();
    state.sessionId.value = 5;
    state.sessionScope.value = "all";

    const fetcher = vi.fn().mockResolvedValue("all-data");

    const { result } = renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    expect(fetcher).toHaveBeenCalledWith(null);
    expect(result.current.data.value).toBe("all-data");
  });

  it("returns loading when current scope and null sessionId", async () => {
    const state = createAppState();
    state.sessionId.value = null;
    state.sessionScope.value = "current";

    const fetcher = vi.fn().mockResolvedValue("should-not-reach");

    const { result } = renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    // Wait a tick for effects to settle
    await new Promise((r) => setTimeout(r, 50));

    // Fetcher should NOT have been called
    expect(fetcher).toHaveBeenCalledTimes(0);

    // Should show loading state
    expect(result.current.loading.value).toBe(true);
    expect(result.current.data.value).toBeNull();
  });

  it("refetches on scope change", async () => {
    const state = createAppState();
    state.sessionId.value = 5;
    state.sessionScope.value = "current";

    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });
    expect(fetcher).toHaveBeenLastCalledWith(5);

    // Switch scope to "all"
    act(() => {
      state.sessionScope.value = "all";
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });
    expect(fetcher).toHaveBeenLastCalledWith(null);
  });

  it("refetches when sessionId changes", async () => {
    const state = createAppState();
    state.sessionId.value = 5;
    state.sessionScope.value = "current";

    const fetcher = vi.fn().mockResolvedValue("data");

    renderHook(() => useScopedApi(fetcher), {
      wrapper: createWrapper(state),
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });
    expect(fetcher).toHaveBeenLastCalledWith(5);

    // Change sessionId (e.g., reconnect with new session)
    act(() => {
      state.sessionId.value = 10;
    });

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });
    expect(fetcher).toHaveBeenLastCalledWith(10);
  });

  it("preserves lazy mode", async () => {
    const state = createAppState();
    state.sessionId.value = 5;
    state.sessionScope.value = "current";

    const fetcher = vi.fn().mockResolvedValue("lazy-data");

    const { result } = renderHook(
      () => useScopedApi(fetcher, { lazy: true }),
      { wrapper: createWrapper(state) },
    );

    await new Promise((r) => setTimeout(r, 50));
    expect(fetcher).toHaveBeenCalledTimes(0);

    // Manual refetch should work
    await act(async () => {
      await result.current.refetch();
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(5);
    expect(result.current.data.value).toBe("lazy-data");
  });
});
