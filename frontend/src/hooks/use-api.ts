import { signal, useSignalEffect, type Signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { useAppState } from "../state/context";

export interface UseApiResult<T> {
  data: Signal<T | null>;
  loading: Signal<boolean>;
  error: Signal<string | null>;
  refetch: () => Promise<void>;
}

/** Shallow-compare two arrays using Object.is (matches React/Preact hook semantics). */
function depsChanged(prev: unknown[], next: unknown[]): boolean {
  if (prev.length !== next.length) return true;
  for (let i = 0; i < prev.length; i++) {
    if (!Object.is(prev[i], next[i])) return true;
  }
  return false;
}

export interface UseApiOptions {
  /** When true, skip the initial fetch on mount. Call `refetch()` manually to load data. */
  lazy?: boolean;
  /** When false, suppress all fetches and hold loading=true. Fetching begins when enabled becomes true. */
  enabled?: boolean;
}

/**
 * Data-fetching hook with signal-based state.
 * Returns signals so only the subscribing components re-render on updates.
 *
 * Pass a `deps` array when the fetcher closes over values that change
 * (e.g., route params). The hook refetches whenever deps change.
 *
 * Pass `{ lazy: true }` to skip the initial mount fetch — useful for
 * expand-on-click patterns where the API call should wait until the
 * user interacts.
 *
 * Pass `{ enabled: false }` to suppress all fetching and hold
 * `loading=true` until `enabled` transitions to `true` — useful when
 * a required dependency (e.g., a session ID) is not yet available.
 *
 * Automatically refetches on WebSocket reconnection via the shared
 * `reconnectVersion` signal. Must be used within AppStateContext.Provider.
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  options: UseApiOptions = {},
): UseApiResult<T> {
  const { lazy = false, enabled = true } = options;

  const data = useRef(signal<T | null>(null)).current;
  const loading = useRef(signal(enabled ? !lazy : true)).current;
  const error = useRef(signal<string | null>(null)).current;

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const requestIdRef = useRef(0);
  /** Tracks whether at least one fetch has been initiated (for reconnect guard). */
  const hasFetchedRef = useRef(false);
  const lazyRef = useRef(lazy);
  const enabledRef = useRef(enabled);

  const refetch = useRef(async () => {
    if (!enabledRef.current) return;
    hasFetchedRef.current = true;
    lazyRef.current = false;
    const id = ++requestIdRef.current;
    loading.value = true;
    error.value = null;
    try {
      const result = await fetcherRef.current();
      if (requestIdRef.current === id) {
        data.value = result;
      }
    } catch (e) {
      if (requestIdRef.current === id) {
        error.value = e instanceof Error ? e.message : "Unknown error";
      }
    } finally {
      if (requestIdRef.current === id) {
        loading.value = false;
      }
    }
  }).current;

  const prevDeps = useRef(deps);
  const depsVersion = useRef(0);
  const prevEnabled = useRef(enabled);

  const depsDidChange = depsChanged(prevDeps.current, deps);
  const enabledDidChange = prevEnabled.current !== enabled;

  if (depsDidChange || enabledDidChange) {
    prevDeps.current = deps;
    prevEnabled.current = enabled;
    enabledRef.current = enabled;

    if (enabled) {
      depsVersion.current++;
      requestIdRef.current++;
      data.value = null;
      loading.value = !lazyRef.current;
      error.value = null;
    } else {
      requestIdRef.current++;
      loading.value = true;
    }
  }

  const version = depsVersion.current;

  useEffect(() => {
    if (!enabledRef.current) return;
    if (lazyRef.current) return;
    void refetch();
  }, [refetch, version]);

  // Auto-refetch on WebSocket reconnection (signal-tracked, no component re-render)
  const { reconnectVersion } = useAppState();
  const mountReconnectVersion = useRef(reconnectVersion.peek());

  useSignalEffect(() => {
    const v = reconnectVersion.value;
    if (v > 0 && v !== mountReconnectVersion.current) {
      if (!enabledRef.current) return;
      if (lazyRef.current && !hasFetchedRef.current) return;
      void refetch();
    }
  });

  return { data, loading, error, refetch };
}
