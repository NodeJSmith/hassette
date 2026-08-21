import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAppStore } from "../state/store";
import { useFakeTimersForEachTest } from "../test/query-test-utils";
import { useRelativeTime } from "./use-relative-time";

describe("useRelativeTime", () => {
  useFakeTimersForEachTest();

  it("returns an empty string for null timestamp", () => {
    const { result } = renderHook(() => useRelativeTime(null));
    expect(result.current).toBe("");
  });

  it("returns a relative time string for a valid timestamp", () => {
    // 5 minutes ago
    const ts = Math.floor(Date.now() / 1000) - 300;
    const { result } = renderHook(() => useRelativeTime(ts));
    expect(result.current).toMatch(/\d+m ago/);
  });

  it("returns an updated string after tick increments", () => {
    // 5 minutes ago — will return "5m ago"
    const ts = Math.floor(Date.now() / 1000) - 300;
    const { result } = renderHook(() => useRelativeTime(ts));
    const initial = result.current;
    expect(initial).toBeTruthy();

    // Advance real time by 60 seconds, then increment tick
    vi.setSystemTime(Date.now() + 60_000);
    act(() => {
      useAppStore.getState().incrementTick();
    });

    // The hook should have re-run and returned a new string
    expect(result.current).not.toBe(initial);
    expect(result.current).toMatch(/\d+m ago/);
  });

  it("re-renders when tick increments even if timestamp hasn't changed", () => {
    const ts = Math.floor(Date.now() / 1000) - 60;
    let renderCount = 0;
    const { result } = renderHook(() => {
      renderCount++;
      return useRelativeTime(ts);
    });

    const initialRenderCount = renderCount;
    act(() => {
      useAppStore.getState().incrementTick();
    });

    // Hook should have re-rendered
    expect(renderCount).toBeGreaterThan(initialRenderCount);
    expect(result.current).toBeTruthy();
  });
});
