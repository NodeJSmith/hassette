import { act, renderHook } from "@testing-library/preact";
import type { ComponentChildren } from "preact";
import { h } from "preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppStateContext } from "../state/context";
import { type AppState, createAppState } from "../state/create-app-state";
import { useRelativeTime } from "./use-relative-time";

function createWrapper(state: AppState) {
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return h(AppStateContext.Provider, { value: state }, children);
  };
}

describe("useRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns an empty string for null timestamp", () => {
    const state = createAppState();
    const { result } = renderHook(() => useRelativeTime(null), {
      wrapper: createWrapper(state),
    });
    expect(result.current).toBe("");
  });

  it("returns a relative time string for a valid timestamp", () => {
    const state = createAppState();
    // 5 minutes ago
    const ts = Math.floor(Date.now() / 1000) - 300;
    const { result } = renderHook(() => useRelativeTime(ts), {
      wrapper: createWrapper(state),
    });
    expect(result.current).toMatch(/\d+m ago/);
  });

  it("returns an updated string after state.tick increments", () => {
    const state = createAppState();
    // 5 minutes ago — will return "5m ago"
    const ts = Math.floor(Date.now() / 1000) - 300;
    const { result } = renderHook(() => useRelativeTime(ts), {
      wrapper: createWrapper(state),
    });
    const initial = result.current;
    expect(initial).toBeTruthy();

    // Advance real time by 60 seconds, then increment tick
    vi.setSystemTime(Date.now() + 60_000);
    act(() => {
      state.tick.value++;
    });

    // The hook should have re-run and returned a new string
    expect(result.current).not.toBe(initial);
    expect(result.current).toMatch(/\d+m ago/);
  });

  it("re-renders when tick increments even if timestamp hasn't changed", () => {
    const state = createAppState();
    const ts = Math.floor(Date.now() / 1000) - 60;
    let renderCount = 0;
    const { result } = renderHook(
      () => {
        renderCount++;
        return useRelativeTime(ts);
      },
      {
        wrapper: createWrapper(state),
      },
    );

    const initialRenderCount = renderCount;
    act(() => {
      state.tick.value++;
    });

    // Hook should have re-rendered
    expect(renderCount).toBeGreaterThan(initialRenderCount);
    expect(result.current).toBeTruthy();
  });
});
