import { useEffect, useRef } from "preact/hooks";

/**
 * Watches the return value of `getValue()` and, when it changes, starts a
 * trailing debounce timer. On timeout, calls `callback()`. The timer resets
 * if the value changes again before it fires, and is cleaned up on unmount.
 *
 * Pass `maxWaitMs` to cap the maximum time between the first change and the
 * callback firing, preventing starvation during rapid-fire updates.
 */
export function useDebouncedEffect(
  getValue: () => unknown,
  delayMs: number,
  callback: () => void,
  maxWaitMs?: number,
): void {
  const value = getValue();
  const prevValueRef = useRef(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    // Skip the initial render — only fire on *changes*
    if (Object.is(prevValueRef.current, value)) {
      return;
    }
    prevValueRef.current = value;

    const fire = () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      if (maxTimerRef.current !== null) {
        clearTimeout(maxTimerRef.current);
        maxTimerRef.current = null;
      }
      callbackRef.current();
    };

    // Clear any pending trailing timer (restart debounce)
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
    }

    timerRef.current = setTimeout(fire, delayMs);

    // Start max-wait timer on the first change only (not already running).
    // Unlike the trailing timer, this does NOT reset on subsequent changes —
    // it guarantees the callback fires within maxWaitMs of the first change.
    if (maxWaitMs !== undefined && maxTimerRef.current === null) {
      maxTimerRef.current = setTimeout(fire, maxWaitMs);
    }

    // Only clean up the trailing timer on re-render — maxWait persists
    // across value changes until it fires or the component unmounts.
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [value, delayMs, maxWaitMs]);

  // Clean up maxWait timer on unmount (separate from the per-change cleanup)
  useEffect(() => {
    return () => {
      if (maxTimerRef.current !== null) {
        clearTimeout(maxTimerRef.current);
        maxTimerRef.current = null;
      }
    };
  }, []);
}
