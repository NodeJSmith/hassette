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
 * Automatically refetches on WebSocket reconnection via the shared
 * `reconnectVersion` signal. Must be used within AppStateContext.Provider.
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  options: UseApiOptions = {},
): UseApiResult<T> {
  const { lazy = false } = options;

  const data = useRef(signal<T | null>(null)).current;
  const loading = useRef(signal(!lazy)).current;
  const error = useRef(signal<string | null>(null)).current;

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const requestIdRef = useRef(0);
  /** Tracks whether at least one fetch has been initiated (for reconnect guard). */
  const hasFetchedRef = useRef(false);
  const lazyRef = useRef(lazy);

  const refetch = useRef(async () => {
    hasFetchedRef.current = true;
    lazyRef.current = false; // After first fetch, allow deps-driven refetches
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

  // Synchronously reset signals and invalidate in-flight requests when deps change
  if (depsChanged(prevDeps.current, deps)) {
    prevDeps.current = deps;
    depsVersion.current++;
    requestIdRef.current++;
    data.value = null;
    loading.value = true;
    error.value = null;
  }

  const version = depsVersion.current;

  useEffect(() => {
    if (lazyRef.current) return;
    void refetch();
  }, [refetch, version]);

  // Auto-refetch on WebSocket reconnection (signal-tracked, no component re-render)
  const { reconnectVersion } = useAppState();
  const mountReconnectVersion = useRef(reconnectVersion.peek());

  useSignalEffect(() => {
    const v = reconnectVersion.value;
    if (v > 0 && v !== mountReconnectVersion.current) {
      // For lazy instances, only reconnect-refetch if at least one fetch has happened
      if (lazyRef.current && !hasFetchedRef.current) return;
      void refetch();
    }
  });

  return { data, loading, error, refetch };
}
