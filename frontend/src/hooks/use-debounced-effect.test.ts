import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { useDebouncedEffect } from "./use-debounced-effect";

describe("useDebouncedEffect", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("fires callback after delay when value changes", () => {
    const source = signal(0);
    const callback = vi.fn();

    renderHook(() =>
      useDebouncedEffect(() => source.value, 500, callback),
    );

    // Initial render should not fire callback (no change yet)
    expect(callback).not.toHaveBeenCalled();

    // Change value
    act(() => {
      source.value = 1;
    });

    // Not yet — timer hasn't elapsed
    expect(callback).not.toHaveBeenCalled();

    // Advance past debounce delay
    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("coalesces rapid changes into a single callback", () => {
    const source = signal(0);
    const callback = vi.fn();

    renderHook(() =>
      useDebouncedEffect(() => source.value, 500, callback),
    );

    // Trigger 5 rapid changes
    for (let i = 1; i <= 5; i++) {
      act(() => {
        source.value = i;
      });
    }

    // Advance past debounce delay
    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("resets timer on new change within delay window", () => {
    const source = signal(0);
    const callback = vi.fn();

    renderHook(() =>
      useDebouncedEffect(() => source.value, 500, callback),
    );

    // First change
    act(() => {
      source.value = 1;
    });

    // Advance 300ms (within debounce window)
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(callback).not.toHaveBeenCalled();

    // Second change — should restart the timer
    act(() => {
      source.value = 2;
    });

    // Advance another 300ms (600ms total, but only 300ms since last change)
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(callback).not.toHaveBeenCalled();

    // Advance remaining 200ms to complete the second debounce window
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("does not fire callback if unmounted before timer elapses", () => {
    const source = signal(0);
    const callback = vi.fn();

    const { unmount } = renderHook(() =>
      useDebouncedEffect(() => source.value, 500, callback),
    );

    // Change value to start debounce
    act(() => {
      source.value = 1;
    });

    // Unmount before timer fires
    unmount();

    // Advance past debounce delay
    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(callback).not.toHaveBeenCalled();
  });

  it("fires at maxWaitMs even during sustained rapid changes", () => {
    const source = signal(0);
    const callback = vi.fn();

    renderHook(() =>
      useDebouncedEffect(() => source.value, 500, callback, 1000),
    );

    // First change starts both trailing (500ms) and maxWait (1000ms) timers
    act(() => { source.value = 1; });
    expect(callback).not.toHaveBeenCalled();

    // Keep changing every 200ms to restart the trailing timer
    // but maxWait should fire at 1000ms regardless
    act(() => { vi.advanceTimersByTime(200); });
    act(() => { source.value = 2; });

    act(() => { vi.advanceTimersByTime(200); });
    act(() => { source.value = 3; });

    act(() => { vi.advanceTimersByTime(200); });
    act(() => { source.value = 4; });

    // 600ms elapsed. Still under maxWait (1000ms), trailing keeps resetting.
    expect(callback).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime(200); });
    act(() => { source.value = 5; });

    // 800ms elapsed. One more change + advance to cross maxWait.
    act(() => { vi.advanceTimersByTime(200); });
    // 1000ms elapsed — maxWait timer fires
    expect(callback).toHaveBeenCalledTimes(1);
  });
});
