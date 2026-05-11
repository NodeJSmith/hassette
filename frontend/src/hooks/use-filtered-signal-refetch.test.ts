import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/preact";
import { signal } from "@preact/signals";
import {
  useFilteredSignalRefetch,
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
} from "./use-filtered-signal-refetch";

describe("useFilteredSignalRefetch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("exports WS_DEBOUNCE_DELAY_MS and WS_DEBOUNCE_MAX_WAIT_MS constants", () => {
    expect(WS_DEBOUNCE_DELAY_MS).toBe(500);
    expect(WS_DEBOUNCE_MAX_WAIT_MS).toBe(1500);
  });

  it("does not fire refetchFn on mount (initial render)", () => {
    const src = signal<string | null>(null);
    const refetchFn = vi.fn();

    renderHook(() =>
      useFilteredSignalRefetch(src, (v) => v !== null, refetchFn, 500, 1500),
    );

    // Advance past any delay to confirm nothing fires on mount
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(refetchFn).not.toHaveBeenCalled();
  });

  it("fires refetchFn after delayMs when filterFn returns true", () => {
    const src = signal<string | null>(null);
    const refetchFn = vi.fn();

    renderHook(() =>
      useFilteredSignalRefetch(src, (v) => v !== null, refetchFn, 500, 1500),
    );

    act(() => {
      src.value = "event";
    });

    // Not yet — timer hasn't elapsed
    expect(refetchFn).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(refetchFn).toHaveBeenCalledTimes(1);
  });

  it("does NOT fire refetchFn when filterFn returns false", () => {
    const src = signal<string | null>(null);
    const refetchFn = vi.fn();

    // Filter: only match "match", not other strings
    renderHook(() =>
      useFilteredSignalRefetch(src, (v) => v === "match", refetchFn, 500, 1500),
    );

    act(() => {
      src.value = "no-match";
    });

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(refetchFn).not.toHaveBeenCalled();
  });

  it("resets trailing timer on rapid matching events", () => {
    const src = signal(0);
    const refetchFn = vi.fn();

    renderHook(() =>
      useFilteredSignalRefetch(src, () => true, refetchFn, 500, 1500),
    );

    // First matching event
    act(() => { src.value = 1; });

    // 300ms later — within debounce window
    act(() => { vi.advanceTimersByTime(300); });
    expect(refetchFn).not.toHaveBeenCalled();

    // Second matching event resets trailing timer
    act(() => { src.value = 2; });

    // 300ms later — only 300ms since last event, not 500ms yet
    act(() => { vi.advanceTimersByTime(300); });
    expect(refetchFn).not.toHaveBeenCalled();

    // Advance remaining 200ms to complete the second debounce window
    act(() => { vi.advanceTimersByTime(200); });
    expect(refetchFn).toHaveBeenCalledTimes(1);
  });

  it("maxWaitMs guarantees firing even during sustained matching events", () => {
    const src = signal(0);
    const refetchFn = vi.fn();

    renderHook(() =>
      useFilteredSignalRefetch(src, () => true, refetchFn, 500, 1500),
    );

    // First matching event starts both trailing (500ms) and maxWait (1500ms) timers
    act(() => { src.value = 1; });
    expect(refetchFn).not.toHaveBeenCalled();

    // Keep changing every 200ms to restart the trailing timer
    // maxWait should fire at 1500ms regardless
    act(() => { vi.advanceTimersByTime(200); });
    act(() => { src.value = 2; });

    act(() => { vi.advanceTimersByTime(200); });
    act(() => { src.value = 3; });

    act(() => { vi.advanceTimersByTime(200); });
    act(() => { src.value = 4; });

    act(() => { vi.advanceTimersByTime(200); });
    act(() => { src.value = 5; });

    act(() => { vi.advanceTimersByTime(200); });
    act(() => { src.value = 6; });

    act(() => { vi.advanceTimersByTime(200); });
    act(() => { src.value = 7; });

    // 1200ms elapsed. Still under maxWait (1500ms), trailing keeps resetting.
    expect(refetchFn).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime(300); });
    // 1500ms elapsed — maxWait timer fires
    expect(refetchFn).toHaveBeenCalledTimes(1);
  });

  it("does not fire refetchFn after unmount (timer cleanup)", () => {
    const src = signal<string | null>(null);
    const refetchFn = vi.fn();

    const { unmount } = renderHook(() =>
      useFilteredSignalRefetch(src, (v) => v !== null, refetchFn, 500, 1500),
    );

    // Start a matching event to start timers
    act(() => { src.value = "event"; });

    // Unmount before timer fires
    unmount();

    // Advance past both timers
    act(() => { vi.advanceTimersByTime(2000); });

    expect(refetchFn).not.toHaveBeenCalled();
  });

  it("mixed events: only matching ones trigger debounce", () => {
    const src = signal<string | null>(null);
    const refetchFn = vi.fn();

    // Only match "app-a"
    renderHook(() =>
      useFilteredSignalRefetch(src, (v) => v === "app-a", refetchFn, 500, 1500),
    );

    // Non-matching event
    act(() => { src.value = "app-b"; });
    act(() => { vi.advanceTimersByTime(600); });
    expect(refetchFn).not.toHaveBeenCalled();

    // Matching event
    act(() => { src.value = "app-a"; });
    act(() => { vi.advanceTimersByTime(500); });
    expect(refetchFn).toHaveBeenCalledTimes(1);

    // Another non-matching
    act(() => { src.value = "app-c"; });
    act(() => { vi.advanceTimersByTime(600); });
    expect(refetchFn).toHaveBeenCalledTimes(1); // still only 1

    // Another matching
    act(() => { src.value = "app-a"; });
    act(() => { vi.advanceTimersByTime(500); });
    expect(refetchFn).toHaveBeenCalledTimes(2);
  });

  it("AC#7: 50 matching events in 5 seconds produces at most 4 refetch calls", () => {
    // delayMs=500, maxWaitMs=1500
    // Events every 100ms for 5000ms = 50 events
    // Theoretical max: ceil(5000 / 1500) = 4 calls (with maxWait bounding)
    const src = signal(0);
    const refetchFn = vi.fn();

    renderHook(() =>
      useFilteredSignalRefetch(src, () => true, refetchFn, 500, 1500),
    );

    // Fire 50 events at 100ms intervals
    for (let i = 1; i <= 50; i++) {
      act(() => {
        vi.advanceTimersByTime(100);
        src.value = i;
      });
    }

    // Let trailing timer settle after the last event
    act(() => { vi.advanceTimersByTime(500); });

    const callCount = refetchFn.mock.calls.length;
    // Must have fired at least once but no more than 4 times
    // (ceil(5000ms / 1500ms maxWait) = 4 max, plus 1 trailing after the burst)
    expect(callCount).toBeGreaterThanOrEqual(1);
    expect(callCount).toBeLessThanOrEqual(4);
  });
});
