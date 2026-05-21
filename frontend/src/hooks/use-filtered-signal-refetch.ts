import { type ReadonlySignal, useSignalEffect } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";

/**
 * Debounce delay for WebSocket-triggered refetches.
 * Trailing edge: the refetch fires 500ms after the last matching WS event.
 */
export const WS_DEBOUNCE_DELAY_MS = 500;

/**
 * Maximum wait for WebSocket-triggered refetches.
 * Caps refetch frequency at one call per 1500ms even during sustained event bursts.
 * Without this, events arriving every 400ms would reset the 500ms trailing timer
 * indefinitely, causing zero refetches during sustained activity.
 */
export const WS_DEBOUNCE_MAX_WAIT_MS = 1500;

/**
 * Subscribes to a Preact signal outside the render cycle (via `useSignalEffect`),
 * applies a filter function, and triggers a debounced refetch callback only when
 * the filter matches. Non-matching signal changes cause zero component re-renders.
 *
 * This replaces the `useDebouncedEffect(() => signal.value, ...)` pattern, which
 * reads `.value` at render time and causes blast-radius re-renders on every WS
 * event from any app.
 *
 * @param signal     The Preact signal to subscribe to (e.g., `invocationCompleted`)
 * @param filterFn   Called synchronously inside the signal effect with the new value.
 *                   Return `true` to start/reset the debounce timer; `false` to skip.
 * @param refetchFn  Called when the debounce timer fires. Should be stable (useCallback
 *                   or a ref-backed function) to avoid resetting timers on re-render.
 * @param delayMs    Trailing debounce delay in milliseconds.
 * @param maxWaitMs  Maximum wait from the first matching event before `refetchFn` is
 *                   forced, even if matching events keep arriving and resetting the
 *                   trailing timer.
 */
export function useFilteredSignalRefetch<T>(
  signal: ReadonlySignal<T>,
  filterFn: (value: T) => boolean,
  refetchFn: () => void,
  delayMs: number,
  maxWaitMs: number,
): void {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refetchFnRef = useRef(refetchFn);
  refetchFnRef.current = refetchFn;
  const filterFnRef = useRef(filterFn);
  filterFnRef.current = filterFn;

  const lastValueRef = useRef<T>(signal.peek());

  useSignalEffect(() => {
    const value = signal.value;

    if (Object.is(value, lastValueRef.current)) {
      return;
    }
    lastValueRef.current = value;

    if (!filterFnRef.current(value)) {
      return;
    }

    const fire = () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      if (maxTimerRef.current !== null) {
        clearTimeout(maxTimerRef.current);
        maxTimerRef.current = null;
      }
      refetchFnRef.current();
    };

    // Reset trailing timer (restart debounce on each matching event).
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(fire, delayMs);

    // Start the max-wait timer only on the first matching event in a burst.
    // It does NOT reset on subsequent matching events — it guarantees the callback
    // fires within maxWaitMs of the first matching event.
    if (maxTimerRef.current === null) {
      maxTimerRef.current = setTimeout(fire, maxWaitMs);
    }
  });

  // Clean up both timers on unmount.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      if (maxTimerRef.current !== null) {
        clearTimeout(maxTimerRef.current);
        maxTimerRef.current = null;
      }
    };
  }, []);
}
