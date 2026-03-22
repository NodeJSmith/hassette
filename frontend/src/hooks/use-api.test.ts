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
