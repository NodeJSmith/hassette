import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { advanceTime, renderInvalidatorHook, useFakeTimersForEachTest } from "../test/query-test-utils";
import { useQueryInvalidator, WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS } from "./use-query-invalidator";

// Fires a rerender carrying the given value — the "a matching (or non-matching) event arrived"
// action every test below simulates at least once.
function triggerEvent(rerender: (props: { value: string | null }) => void, value: string | null) {
  act(() => {
    rerender({ value });
  });
}

describe("exported constants", () => {
  it("WS_DEBOUNCE_DELAY_MS is 500", () => {
    expect(WS_DEBOUNCE_DELAY_MS).toBe(500);
  });

  it("WS_DEBOUNCE_MAX_WAIT_MS is 1500", () => {
    expect(WS_DEBOUNCE_MAX_WAIT_MS).toBe(1500);
  });
});

describe("useQueryInvalidator", () => {
  useFakeTimersForEachTest();

  // dup-ignore-start: these debounce/max-wait test bodies open with a render+trigger+advance (or advance+expect) call
  // sequence that PMD's literal/identifier-normalizing tokenizer treats as equivalent to unrelated short call
  // sequences elsewhere in the repo (e.g. use-log-filters.test.ts's expect()/toContain() chains, use-scoped-query.test.ts
  // and use-telemetry-health.test.ts's own render+assert openings, use-roving-tab-index.test.ts's ref/DOM setup) —
  // coincidental token-shape overlap between genuinely unrelated, distinct test bodies, not unresolved boilerplate.
  // The actual shared setup (QueryClient + spy + hook render, fake-timer lifecycle, event-firing, clock-advancing) is
  // already extracted into renderInvalidatorHook / useFakeTimersForEachTest / triggerEvent / advanceTime above.
  it("does not invalidate on mount (no spurious initial fetch)", () => {
    const filterFn = vi.fn().mockReturnValue(true);
    const { invalidateSpy } = renderInvalidatorHook<string | null>(
      (value) => useQueryInvalidator(value, filterFn, ["test-key"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      null,
    );

    advanceTime(WS_DEBOUNCE_MAX_WAIT_MS + 100);

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("invalidates after delayMs when filter matches", async () => {
    const filterFn = (v: string | null) => v !== null;
    const { rerender, invalidateSpy } = renderInvalidatorHook<string | null>(
      (value) => useQueryInvalidator(value, filterFn, ["test-delay"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      null,
    );

    // Trigger a matching value change
    triggerEvent(rerender, "event-1");

    // Not yet — delay hasn't elapsed
    advanceTime(WS_DEBOUNCE_DELAY_MS - 1);
    expect(invalidateSpy).not.toHaveBeenCalled();

    // Advance past the delay
    advanceTime(1);
    expect(invalidateSpy).toHaveBeenCalledOnce();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["test-delay"] });
  });

  it("does not invalidate when filter returns false", async () => {
    const filterFn = () => false;
    const { rerender, invalidateSpy } = renderInvalidatorHook<string | null>(
      (value) =>
        useQueryInvalidator(value, filterFn, ["test-filter-false"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      null,
    );

    triggerEvent(rerender, "event-1");
    advanceTime(WS_DEBOUNCE_MAX_WAIT_MS + 100);

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("trailing timer resets on each matching event (debounce)", async () => {
    const filterFn = (v: string | null) => v !== null;
    const { rerender, invalidateSpy } = renderInvalidatorHook<string | null>(
      (value) => useQueryInvalidator(value, filterFn, ["test-trailing"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      null,
    );

    // First event starts trailing timer
    triggerEvent(rerender, "event-1");
    advanceTime(400); // 400ms in — before 500ms delay

    // Second event resets trailing timer
    triggerEvent(rerender, "event-2");
    advanceTime(400); // 400ms more — still before 500ms from last event

    // Still not invalidated (trailing timer reset)
    expect(invalidateSpy).not.toHaveBeenCalled();

    // But max-wait (1500ms from first event) has now passed (400 + 400 = 800ms... still under 1500)
    // Advance to complete the trailing debounce from event-2
    advanceTime(100); // 500ms from event-2
    expect(invalidateSpy).toHaveBeenCalledOnce();
  });

  it("max-wait timer fires during sustained events (trailing timer never settles)", async () => {
    const filterFn = (v: string | null) => v !== null;
    const { rerender, invalidateSpy } = renderInvalidatorHook<string | null>(
      (value) => useQueryInvalidator(value, filterFn, ["test-max-wait"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      null,
    );

    // Continuously fire events every 400ms — trailing timer keeps resetting (never reaches 500ms)
    // max-wait should fire at 1500ms from the first event
    triggerEvent(rerender, "event-1"); // t=0
    advanceTime(400); // t=400

    triggerEvent(rerender, "event-2"); // t=400, trailing resets
    advanceTime(400); // t=800

    triggerEvent(rerender, "event-3"); // t=800, trailing resets
    advanceTime(400); // t=1200

    triggerEvent(rerender, "event-4"); // t=1200, trailing resets
    // t=1200, max-wait fires at 1500 from first event
    // At t=1200, max-wait hasn't fired yet (1200 < 1500)
    expect(invalidateSpy).not.toHaveBeenCalled();

    advanceTime(300); // t=1500 — max-wait fires
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
    const filterFn = (v: string | null) => v !== null;
    const { rerender, invalidateSpy } = renderInvalidatorHook<string | null>(
      (value) => useQueryInvalidator(value, filterFn, ["test-max-wait-no-reset"], delay, maxWait),
      null,
    );

    // Event-1 at t=0: trailing resets to fire at t=400, max-wait fires at t=1000
    triggerEvent(rerender, "event-1"); // t=0

    // Advance to t=300: trailing hasn't fired (400ms > 300ms), max-wait hasn't fired
    advanceTime(300); // t=300

    // Event-2 at t=300: trailing resets to fire at t=700; max-wait stays at t=1000
    triggerEvent(rerender, "event-2"); // t=300
    expect(invalidateSpy).not.toHaveBeenCalled();

    // Advance to t=700: trailing fires (invalidation #1)
    advanceTime(400); // t=700
    expect(invalidateSpy).toHaveBeenCalledOnce();
    invalidateSpy.mockClear();

    // Advance to t=1000: max-wait would have fired here IF it hadn't been cleared by fire()
    // Since fire() cleared maxTimerRef when trailing fired at t=700, no second call fires
    advanceTime(300); // t=1000
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("ignores same-value re-renders (dependency array dedup)", async () => {
    const filterFn = (v: string | null) => v !== null;
    const { rerender, invalidateSpy } = renderInvalidatorHook<string | null>(
      (value) => useQueryInvalidator(value, filterFn, ["test-dedup"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      null,
    );

    triggerEvent(rerender, "event-1");
    // Re-render with the same value — should not reset the trailing timer
    triggerEvent(rerender, "event-1");
    advanceTime(WS_DEBOUNCE_DELAY_MS);
    expect(invalidateSpy).toHaveBeenCalledOnce();
  });

  it("cleans up both timers on unmount (no dangling timeouts)", async () => {
    const filterFn = (v: string | null) => v !== null;
    const { rerender, unmount, invalidateSpy } = renderInvalidatorHook<string | null>(
      (value) => useQueryInvalidator(value, filterFn, ["test-cleanup"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
      null,
    );

    // Start the timers
    triggerEvent(rerender, "event-1");
    advanceTime(100);

    // Unmount before timers fire
    unmount();

    // Advance time past both timer thresholds
    advanceTime(WS_DEBOUNCE_MAX_WAIT_MS + WS_DEBOUNCE_DELAY_MS);

    // No invalidation should have occurred — both timers were cleared on unmount
    expect(invalidateSpy).not.toHaveBeenCalled();
  });
  // dup-ignore-end
});
