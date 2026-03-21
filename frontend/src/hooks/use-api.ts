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
 */
export function useApi<T>(fetcher: () => Promise<T>): UseApiResult<T> {
  const data = useRef(signal<T | null>(null)).current;
  const loading = useRef(signal(true)).current;
  const error = useRef(signal<string | null>(null)).current;

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refetch = useRef(async () => {
    loading.value = true;
    error.value = null;
    try {
      data.value = await fetcherRef.current();
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Unknown error";
    } finally {
      loading.value = false;
    }
  }).current;

  useEffect(() => {
    void refetch();
  }, [refetch]);

  return { data, loading, error, refetch };
}
