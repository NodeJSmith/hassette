import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";

import { getRecentLogs, type LogEntry } from "@/api/endpoints";
import { useScopedQuery } from "@/hooks/use-scoped-query";
import { queryKeys } from "@/lib/query-keys";
import { useAppStore } from "@/state/store";

import { REST_FETCH_LIMIT } from "./constants";

interface UseLogDataParams {
  appKey?: string;
  executionId?: string | null;
}

interface UseLogDataResult {
  /** Exactly what the latest `GET /logs/recent` response says — the query result replaces the
   * cache on every fetch (TanStack's default), there is no merge and no client-side cursor. */
  allEntries: LogEntry[];
  loading: boolean;
}

// Stable empty-array identity for the "no data yet" case — `data ?? []` would otherwise allocate
// a fresh array every render while `data` is undefined, churning `useLogFilters`' downstream
// memoization (which keys off `allEntries`' reference).
const EMPTY_ENTRIES: LogEntry[] = [];

// Debounce-with-maxWait for coalescing bursty `log_hint` messages into one refetch. Each hint
// resets the debounce timer; maxWait guarantees a refetch fires at least this often even under a
// continuous burst, so the table isn't silenced for the whole burst duration.
export const HINT_DEBOUNCE_MS = 200;
export const HINT_MAX_WAIT_MS = 500;

// Bounded fallback re-sync, independent of hint activity: a hint that arrives before the DB write
// it's announcing actually commits (design.md's documented race) is only recovered by a later
// hint sweeping it in. If logging then goes quiet, no further hint ever arrives to do that. This
// periodic refetch runs regardless of hint activity so that window is always bounded.
export const PERIODIC_RESYNC_MS = 5000;

/**
 * Live log table data source: the current `GET /logs/recent` response, kept fresh by a
 * `log_hint` WS notification (debounced), a periodic fallback tick, and (via the base query's
 * own cache key) a WS reconnect's unfiltered `invalidateQueries()` in `use-websocket.ts`.
 *
 * Every fetch **replaces** the cached view — no merge, no cursor, no reset detection. The
 * server's response is always the truth for what's on screen; see design.md's 2026-09-27
 * addendum for why the earlier cursor-based catch-up design was replaced with this.
 */
export function useLogData({ appKey, executionId }: UseLogDataParams): UseLogDataResult {
  const queryClient = useQueryClient();
  const logHintVersion = useAppStore((s) => s.logHintVersion);

  const baseKey = useMemo(() => queryKeys.recentLogs(appKey, executionId), [appKey, executionId]);

  const { data, isPending, isError, error } = useScopedQuery<LogEntry[]>(
    baseKey,
    (since, signal) => getRecentLogs({ appKey, executionId, since, limit: REST_FETCH_LIMIT }, signal),
    { refetchInterval: PERIODIC_RESYNC_MS },
  );

  // Toast once per outage, not once per failed fetch: every failed refetch (including each
  // PERIODIC_RESYNC_MS tick) produces a fresh `error` object, so an ungated effect would re-toast
  // every few seconds for the whole outage. Re-arms on the first successful fetch.
  const toastedErrorRef = useRef(false);
  useEffect(() => {
    if (!isError || !error) {
      toastedErrorRef.current = false;
      return;
    }
    if (toastedErrorRef.current) return;
    toastedErrorRef.current = true;
    toast.error(error instanceof Error ? error.message : "Failed to load recent logs");
  }, [isError, error]);

  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxWaitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevHintVersionRef = useRef(logHintVersion);

  useEffect(
    () => () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      if (maxWaitTimerRef.current) clearTimeout(maxWaitTimerRef.current);
    },
    [],
  );

  useEffect(() => {
    // Skip on mount (and on any render where the version didn't actually change) — a newly
    // mounted view's base query above already fetches fresh, so it needs no extra refetch.
    if (logHintVersion === prevHintVersionRef.current) return;
    prevHintVersionRef.current = logHintVersion;

    const runInvalidate = () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
      if (maxWaitTimerRef.current) {
        clearTimeout(maxWaitTimerRef.current);
        maxWaitTimerRef.current = null;
      }
      // invalidateQueries, not query.refetch() — refetch() ignores `enabled` and would fire
      // even while the base query is disabled (e.g. a since-restart view still waiting on
      // uptime). invalidateQueries respects `enabled`: it marks the entry stale and, once the
      // query is enabled, TanStack refetches it on its own.
      //
      // cancelRefetch: false — invalidateQueries defaults to cancelling any fetch already in
      // flight before starting its own. Under sustained hint traffic, if a single /logs/recent
      // fetch takes longer than HINT_MAX_WAIT_MS, every fetch would get cancelled by the next
      // hint's invalidate before it ever resolves, and the table would silently stop updating.
      // Letting the in-flight fetch finish (its result still lands in the cache) and skipping
      // the redundant duplicate is strictly better here — there's no query-arg change to pick up
      // by re-issuing, since baseKey/since are unchanged between one hint and the next.
      void queryClient.invalidateQueries({ queryKey: baseKey }, { cancelRefetch: false });
    };

    if (!maxWaitTimerRef.current) {
      maxWaitTimerRef.current = setTimeout(runInvalidate, HINT_MAX_WAIT_MS);
    }
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(runInvalidate, HINT_DEBOUNCE_MS);
  }, [logHintVersion, queryClient, baseKey]);

  return { allEntries: data ?? EMPTY_ENTRIES, loading: isPending };
}
