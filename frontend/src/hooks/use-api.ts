import { signal, type Signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";

export interface UseApiResult<T> {
  data: Signal<T | null>;
  loading: Signal<boolean>;
  error: Signal<string | null>;
  refetch: () => Promise<void>;
}

/**
 * Data-fetching hook with signal-based state.
 * Returns signals so only the subscribing components re-render on updates.
 *
 * Pass a `deps` array when the fetcher closes over values that change
 * (e.g., route params). The hook refetches whenever deps change.
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): UseApiResult<T> {
  const data = useRef(signal<T | null>(null)).current;
  const loading = useRef(signal(true)).current;
  const error = useRef(signal<string | null>(null)).current;

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const requestIdRef = useRef(0);

  const refetch = useRef(async () => {
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

  const depsKey = JSON.stringify(deps);
  const prevDepsKey = useRef(depsKey);

  // Synchronously reset signals when deps change to prevent stale data flash
  if (prevDepsKey.current !== depsKey) {
    prevDepsKey.current = depsKey;
    data.value = null;
    loading.value = true;
    error.value = null;
  }

  useEffect(() => {
    void refetch();
  }, [refetch, depsKey]);

  return { data, loading, error, refetch };
}
