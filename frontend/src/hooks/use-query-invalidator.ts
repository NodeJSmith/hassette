import { type ReadonlySignal, useSignalEffect } from "@preact/signals";
import { useQueryClient } from "@tanstack/preact-query";
import { useEffect, useRef } from "preact/hooks";

/**
 * Debounce delay for WebSocket-triggered cache invalidations.
 * Trailing edge: invalidation fires 500ms after the last matching WS event.
 */
export const WS_DEBOUNCE_DELAY_MS = 500;

/**
 * Maximum wait for WebSocket-triggered cache invalidations.
 * Caps invalidation frequency at one call per 1500ms even during sustained event bursts.
 * Without this, events arriving every 400ms would reset the 500ms trailing timer
 * indefinitely, causing zero invalidations during sustained activity.
 */
export const WS_DEBOUNCE_MAX_WAIT_MS = 1500;

/**
 * Subscribes to a Preact signal, applies a filter function, and calls
 * `queryClient.invalidateQueries({ queryKey })` after a debounce.
 *
 * Debounce algorithm:
 * - Trailing timer: resets on each matching event; fires `delayMs` after the last event.
 * - Max-wait timer: starts on the first matching event; fires after `maxWaitMs` regardless
 *   of subsequent events. Does NOT reset on subsequent matching events.
 */
export function useQueryInvalidator<T>(
  signal: ReadonlySignal<T>,
  filterFn: (value: T) => boolean,
  queryKey: readonly unknown[],
  delayMs: number = WS_DEBOUNCE_DELAY_MS,
  maxWaitMs: number = WS_DEBOUNCE_MAX_WAIT_MS,
): void {
  const queryClient = useQueryClient();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const queryClientRef = useRef(queryClient);
  queryClientRef.current = queryClient;
  const queryKeyRef = useRef(queryKey);
  queryKeyRef.current = queryKey;
  const delayMsRef = useRef(delayMs);
  delayMsRef.current = delayMs;
  const maxWaitMsRef = useRef(maxWaitMs);
  maxWaitMsRef.current = maxWaitMs;

  const filterFnRef = useRef(filterFn);
  filterFnRef.current = filterFn;
  const lastValueRef = useRef<T>(signal.peek());

  const fireRef = useRef(() => {});
  fireRef.current = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (maxTimerRef.current !== null) {
      clearTimeout(maxTimerRef.current);
      maxTimerRef.current = null;
    }
    void queryClientRef.current.invalidateQueries({ queryKey: queryKeyRef.current });
  };

  useSignalEffect(() => {
    const value = signal.value;
    if (Object.is(value, lastValueRef.current)) return;
    lastValueRef.current = value;
    if (!filterFnRef.current(value)) return;

    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(() => fireRef.current(), delayMsRef.current);

    if (maxTimerRef.current === null) {
      maxTimerRef.current = setTimeout(() => fireRef.current(), maxWaitMsRef.current);
    }
  });

  const serializedKey = JSON.stringify(queryKey);
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
  }, [serializedKey]);
}
