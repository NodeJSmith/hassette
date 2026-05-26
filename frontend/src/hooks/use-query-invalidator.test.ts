import { signal } from "@preact/signals";
import { act } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createTestQueryClient, renderHookWithProviders } from "../test/query-test-utils";
import { useQueryInvalidator, WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS } from "./use-query-invalidator";

describe("exported constants", () => {
  it("WS_DEBOUNCE_DELAY_MS is 500", () => {
    expect(WS_DEBOUNCE_DELAY_MS).toBe(500);
  });

  it("WS_DEBOUNCE_MAX_WAIT_MS is 1500", () => {
    expect(WS_DEBOUNCE_MAX_WAIT_MS).toBe(1500);
  });
});

describe("useQueryInvalidator", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not invalidate on mount (no spurious initial fetch)", () => {
    const sig = signal<string | null>(null);
    const filterFn = vi.fn().mockReturnValue(true);
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderHookWithProviders(
      () => useQueryInvalidator(sig, filterFn, ["test-key"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      { queryClient },
    );

    act(() => {
      vi.advanceTimersByTime(WS_DEBOUNCE_MAX_WAIT_MS + 100);
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("invalidates after delayMs when filter matches", async () => {
    const sig = signal<string | null>(null);
    const filterFn = (v: string | null) => v !== null;
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderHookWithProviders(
      () => useQueryInvalidator(sig, filterFn, ["test-delay"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      { queryClient },
    );

    // Trigger a matching signal change
    act(() => {
      sig.value = "event-1";
    });

    // Not yet — delay hasn't elapsed
    act(() => {
      vi.advanceTimersByTime(WS_DEBOUNCE_DELAY_MS - 1);
    });
    expect(invalidateSpy).not.toHaveBeenCalled();

    // Advance past the delay
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(invalidateSpy).toHaveBeenCalledOnce();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["test-delay"] });
  });

  it("does not invalidate when filter returns false", async () => {
    const sig = signal<string | null>(null);
    const filterFn = () => false;
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderHookWithProviders(
      () => useQueryInvalidator(sig, filterFn, ["test-filter-false"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      { queryClient },
    );

    act(() => {
      sig.value = "event-1";
    });
    act(() => {
      vi.advanceTimersByTime(WS_DEBOUNCE_MAX_WAIT_MS + 100);
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("trailing timer resets on each matching event (debounce)", async () => {
    const sig = signal<string | null>(null);
    const filterFn = (v: string | null) => v !== null;
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderHookWithProviders(
      () => useQueryInvalidator(sig, filterFn, ["test-trailing"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      { queryClient },
    );

    // First event starts trailing timer
    act(() => {
      sig.value = "event-1";
    });
    act(() => {
      vi.advanceTimersByTime(400);
    }); // 400ms in — before 500ms delay

    // Second event resets trailing timer
    act(() => {
      sig.value = "event-2";
    });
    act(() => {
      vi.advanceTimersByTime(400);
    }); // 400ms more — still before 500ms from last event

    // Still not invalidated (trailing timer reset)
    expect(invalidateSpy).not.toHaveBeenCalled();

    // But max-wait (1500ms from first event) has now passed (400 + 400 = 800ms... still under 1500)
    // Advance to complete the trailing debounce from event-2
    act(() => {
      vi.advanceTimersByTime(100);
    }); // 500ms from event-2
    expect(invalidateSpy).toHaveBeenCalledOnce();
  });

  it("max-wait timer fires during sustained events (trailing timer never settles)", async () => {
    const sig = signal<string | null>(null);
    const filterFn = (v: string | null) => v !== null;
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderHookWithProviders(
      () => useQueryInvalidator(sig, filterFn, ["test-max-wait"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      { queryClient },
    );

    // Continuously fire events every 400ms — trailing timer keeps resetting (never reaches 500ms)
    // max-wait should fire at 1500ms from the first event
    act(() => {
      sig.value = "event-1";
    }); // t=0
    act(() => {
      vi.advanceTimersByTime(400);
    }); // t=400

    act(() => {
      sig.value = "event-2";
    }); // t=400, trailing resets
    act(() => {
      vi.advanceTimersByTime(400);
    }); // t=800

    act(() => {
      sig.value = "event-3";
    }); // t=800, trailing resets
    act(() => {
      vi.advanceTimersByTime(400);
    }); // t=1200

    act(() => {
      sig.value = "event-4";
    }); // t=1200, trailing resets
    // t=1200, max-wait fires at 1500 from first event
    // At t=1200, max-wait hasn't fired yet (1200 < 1500)
    expect(invalidateSpy).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(300);
    }); // t=1500 — max-wait fires
    expect(invalidateSpy).toHaveBeenCalledOnce();
  });

  it("trailing fire clears max-wait timer so it does not double-fire", async () => {
    // Use custom delays to make the invariant verifiable:
    // trailing = 400ms, max-wait = 1000ms
    // Events arrive at t=0 and t=300 (faster than trailing delay).
    // - If max-wait resets on event-2: max-wait would fire at t=300+1000=1300
    // - If max-wait does NOT reset (correct): max-wait fires at t=0+1000=1000
    // We verify invalidation happens at t=1000, NOT at t=1300.
    const delay = 400;
    const maxWait = 1000;
    const sig = signal<string | null>(null);
    const filterFn = (v: string | null) => v !== null;
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderHookWithProviders(() => useQueryInvalidator(sig, filterFn, ["test-max-wait-no-reset"], delay, maxWait), {
      queryClient,
    });

    // Event-1 at t=0: trailing resets to fire at t=400, max-wait fires at t=1000
    act(() => {
      sig.value = "event-1";
    }); // t=0

    // Advance to t=300: trailing hasn't fired (400ms > 300ms), max-wait hasn't fired
    act(() => {
      vi.advanceTimersByTime(300);
    }); // t=300

    // Event-2 at t=300: trailing resets to fire at t=700; max-wait stays at t=1000
    act(() => {
      sig.value = "event-2";
    }); // t=300
    expect(invalidateSpy).not.toHaveBeenCalled();

    // Advance to t=700: trailing fires (invalidation #1)
    act(() => {
      vi.advanceTimersByTime(400);
    }); // t=700
    expect(invalidateSpy).toHaveBeenCalledOnce();
    invalidateSpy.mockClear();

    // Advance to t=1000: max-wait would have fired here IF it hadn't been cleared by fire()
    // Since fire() cleared maxTimerRef when trailing fired at t=700, no second call fires
    act(() => {
      vi.advanceTimersByTime(300);
    }); // t=1000
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("ignores same-value signal updates (deduplication via Object.is)", async () => {
    const sig = signal<string | null>(null);
    const filterFn = (v: string | null) => v !== null;
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderHookWithProviders(
      () => useQueryInvalidator(sig, filterFn, ["test-dedup"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      { queryClient },
    );

    act(() => {
      sig.value = "event-1";
    });
    // Re-assign the same value — should not reset trailing timer
    act(() => {
      sig.value = "event-1";
    });
    act(() => {
      vi.advanceTimersByTime(WS_DEBOUNCE_DELAY_MS);
    });
    expect(invalidateSpy).toHaveBeenCalledOnce();
  });

  it("cleans up both timers on unmount (no dangling timeouts)", async () => {
    const sig = signal<string | null>(null);
    const filterFn = (v: string | null) => v !== null;
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { unmount } = renderHookWithProviders(
      () => useQueryInvalidator(sig, filterFn, ["test-cleanup"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      { queryClient },
    );

    // Start the timers
    act(() => {
      sig.value = "event-1";
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });

    // Unmount before timers fire
    unmount();

    // Advance time past both timer thresholds
    act(() => {
      vi.advanceTimersByTime(WS_DEBOUNCE_MAX_WAIT_MS + WS_DEBOUNCE_DELAY_MS);
    });

    // No invalidation should have occurred — both timers were cleared on unmount
    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});

describe("useQueryInvalidator (multi-signal)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function setupMultiSignal(queryKey: string) {
    const sigA = signal<string | null>(null);
    const sigB = signal<number | null>(null);
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const result = renderHookWithProviders(
      () =>
        useQueryInvalidator(
          [
            [sigA, (v: unknown) => v !== null],
            [sigB, (v: unknown) => v !== null],
          ],
          [queryKey],
          WS_DEBOUNCE_DELAY_MS,
          WS_DEBOUNCE_MAX_WAIT_MS,
        ),
      { queryClient },
    );

    return { sigA, sigB, invalidateSpy, ...result };
  }

  it("two signals sharing a key produce exactly one invalidation within the debounce window", () => {
    const { sigA, sigB, invalidateSpy } = setupMultiSignal("shared-key");

    act(() => {
      sigA.value = "event-a";
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    act(() => {
      sigB.value = 42;
    });

    act(() => {
      vi.advanceTimersByTime(WS_DEBOUNCE_DELAY_MS);
    });

    expect(invalidateSpy).toHaveBeenCalledOnce();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["shared-key"] });
  });

  it("signal A firing alone triggers invalidation", () => {
    const { sigA, invalidateSpy } = setupMultiSignal("solo-a");

    act(() => {
      sigA.value = "only-a";
    });
    act(() => {
      vi.advanceTimersByTime(WS_DEBOUNCE_DELAY_MS);
    });

    expect(invalidateSpy).toHaveBeenCalledOnce();
  });

  it("signal B firing alone triggers invalidation", () => {
    const { sigB, invalidateSpy } = setupMultiSignal("solo-b");

    act(() => {
      sigB.value = 99;
    });
    act(() => {
      vi.advanceTimersByTime(WS_DEBOUNCE_DELAY_MS);
    });

    expect(invalidateSpy).toHaveBeenCalledOnce();
  });

  it("rapid alternating events from both signals — max-wait fires exactly once", () => {
    const { sigA, sigB, invalidateSpy } = setupMultiSignal("alternating");

    act(() => {
      sigA.value = "a1";
    }); // t=0
    act(() => {
      vi.advanceTimersByTime(400);
    }); // t=400
    act(() => {
      sigB.value = 1;
    }); // t=400
    act(() => {
      vi.advanceTimersByTime(400);
    }); // t=800
    act(() => {
      sigA.value = "a2";
    }); // t=800
    act(() => {
      vi.advanceTimersByTime(400);
    }); // t=1200
    act(() => {
      sigB.value = 2;
    }); // t=1200

    expect(invalidateSpy).not.toHaveBeenCalled();

    // Max-wait fires at t=1500
    act(() => {
      vi.advanceTimersByTime(300);
    }); // t=1500
    expect(invalidateSpy).toHaveBeenCalledOnce();
  });

  it("cleans up timers on unmount with no dangling callbacks", () => {
    const { sigA, sigB, unmount, invalidateSpy } = setupMultiSignal("cleanup-multi");

    act(() => {
      sigA.value = "start";
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    act(() => {
      sigB.value = 1;
    });

    unmount();

    act(() => {
      vi.advanceTimersByTime(WS_DEBOUNCE_MAX_WAIT_MS + WS_DEBOUNCE_DELAY_MS);
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("does not invalidate on mount (no spurious initial fetch)", () => {
    const { invalidateSpy } = setupMultiSignal("no-mount-fire");

    act(() => {
      vi.advanceTimersByTime(WS_DEBOUNCE_MAX_WAIT_MS + 100);
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});
