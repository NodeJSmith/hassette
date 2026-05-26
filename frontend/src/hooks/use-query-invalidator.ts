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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SignalFilterPair = readonly [ReadonlySignal<any>, (value: any) => boolean];

/**
 * Subscribes to one or more Preact signals, applies filter functions, and calls
 * `queryClient.invalidateQueries({ queryKey })` after a debounce.
 *
 * Debounce algorithm:
 * - Trailing timer: resets on each matching event; fires `delayMs` after the last event.
 * - Max-wait timer: starts on the first matching event; fires after `maxWaitMs` regardless
 *   of subsequent events. Does NOT reset on subsequent matching events.
 *
 * The multi-signal overload shares a single debounce timer across all signals — two
 * signals firing within the debounce window produce exactly one `invalidateQueries` call.
 */
export function useQueryInvalidator<T>(
  signal: ReadonlySignal<T>,
  filterFn: (value: T) => boolean,
  queryKey: readonly unknown[],
  delayMs?: number,
  maxWaitMs?: number,
): void;

export function useQueryInvalidator(
  signals: readonly SignalFilterPair[],
  queryKey: readonly unknown[],
  delayMs?: number,
  maxWaitMs?: number,
): void;

export function useQueryInvalidator<T>(
  signalOrSignals: ReadonlySignal<T> | readonly SignalFilterPair[],
  filterFnOrQueryKey: ((value: T) => boolean) | readonly unknown[],
  queryKeyOrDelayMs?: readonly unknown[] | number,
  delayMsOrMaxWaitMs?: number,
  maxWaitMsArg?: number,
): void {
  let pairs: readonly SignalFilterPair[];
  let queryKey: readonly unknown[];
  let delayMs: number;
  let maxWaitMs: number;

  if (Array.isArray(signalOrSignals)) {
    pairs = signalOrSignals as readonly SignalFilterPair[];
    queryKey = filterFnOrQueryKey as readonly unknown[];
    delayMs = (queryKeyOrDelayMs as number | undefined) ?? WS_DEBOUNCE_DELAY_MS;
    maxWaitMs = delayMsOrMaxWaitMs ?? WS_DEBOUNCE_MAX_WAIT_MS;
  } else {
    const sig = signalOrSignals as ReadonlySignal<T>;
    const fn = filterFnOrQueryKey as (value: T) => boolean;
    pairs = [[sig, fn as (value: unknown) => boolean]];
    queryKey = queryKeyOrDelayMs as readonly unknown[];
    delayMs = delayMsOrMaxWaitMs ?? WS_DEBOUNCE_DELAY_MS;
    maxWaitMs = maxWaitMsArg ?? WS_DEBOUNCE_MAX_WAIT_MS;
  }

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

  const pairsRef = useRef(pairs);
  pairsRef.current = pairs;
  const lastValuesRef = useRef<unknown[]>(pairs.map(([s]) => s.peek()));
  if (lastValuesRef.current.length !== pairs.length) {
    lastValuesRef.current = pairs.map(([s]) => s.peek());
  }

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
    let shouldFire = false;
    for (let i = 0; i < pairsRef.current.length; i++) {
      const value = pairsRef.current[i][0].value;
      if (!Object.is(value, lastValuesRef.current[i])) {
        lastValuesRef.current[i] = value;
        if (pairsRef.current[i][1](value)) {
          shouldFire = true;
        }
      }
    }
    if (!shouldFire) return;

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
