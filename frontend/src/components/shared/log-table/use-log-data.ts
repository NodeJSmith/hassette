import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";

import { getLogsSince, getRecentLogs, type LogEntry } from "@/api/endpoints";
import { useScopedQuery } from "@/hooks/use-scoped-query";
import { queryKeys } from "@/lib/query-keys";
import { useAppStore } from "@/state/store";
import { resolveSince } from "@/utils/time-window";

import { MAX_CACHED_LOG_ENTRIES, REST_FETCH_LIMIT } from "./constants";
import { rowKey } from "./types";

interface UseLogDataParams {
  appKey?: string;
  executionId?: string | null;
}

interface UseLogDataResult {
  /** REST entries, including hint-triggered catch-up merges. Kept alongside `restEntries` — both
   * are currently identical, since there is no more WS-pushed content to distinguish them from —
   * so downstream consumers (`use-log-filters.ts`'s livePaused freeze) don't need to change. */
  allEntries: LogEntry[];
  restEntries: LogEntry[];
  loading: boolean;
}

// Debounce-with-maxWait for coalescing bursty `log_hint` messages into one REST fetch. Each hint
// resets the debounce timer; maxWait guarantees a fetch fires at least this often even under a
// continuous burst, so the table isn't silenced for the whole burst duration.
const HINT_DEBOUNCE_MS = 200;
const HINT_MAX_WAIT_MS = 500;

// Bounds for the catch-up loop that follows a full-page response — a full page means there may
// be more records beyond the page just fetched.
const CATCH_UP_MAX_PAGES = 5;
const CATCH_UP_MIN_DELAY_MS = 100;

// Mirrors the WS reconnect backoff constants in use-websocket.ts (INITIAL_BACKOFF_MS=1000,
// MAX_BACKOFF_MS=30000, BACKOFF_MULTIPLIER=1.5) — same shape, applied to catch-up fetch retries on
// non-2xx responses instead of WS reconnect attempts. Not imported directly: those constants are
// module-local to use-websocket.ts.
const CATCH_UP_INITIAL_BACKOFF_MS = 1000;
const CATCH_UP_MAX_BACKOFF_MS = 30_000;
const CATCH_UP_BACKOFF_MULTIPLIER = 1.5;
const CATCH_UP_MAX_RETRIES = 3;

interface CatchUpFilters {
  appKey?: string;
  executionId?: string | null;
  since: number;
}

interface CatchUpContext extends CatchUpFilters {
  scopedKey: readonly unknown[];
  waitingForUptime: boolean;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function maxId(entries: readonly LogEntry[]): number {
  return entries.length ? Math.max(...entries.map((e) => e.id)) : 0;
}

/** Fetches one page from `GET /logs/since/{sinceId}` via `queryClient.fetchQuery`, so TanStack's
 * error-state propagation applies. Retries on failure with the backoff shape described above; a
 * distinct `queryKey` per attempt keeps this fetch out of the base query's cache entry — the
 * caller merges the successful result into that entry explicitly. */
async function fetchSinceWithBackoff(
  queryClient: QueryClient,
  scopedKey: readonly unknown[],
  sinceId: number,
  filters: CatchUpFilters,
): Promise<LogEntry[]> {
  let attempt = 0;
  let delayMs = CATCH_UP_INITIAL_BACKOFF_MS;

  while (true) {
    try {
      return await queryClient.fetchQuery<LogEntry[]>({
        queryKey: [...scopedKey, "since", sinceId, attempt],
        queryFn: ({ signal }) => getLogsSince(sinceId, { ...filters, limit: REST_FETCH_LIMIT }, signal),
        staleTime: 0,
        gcTime: 0,
        retry: false,
      });
    } catch (err) {
      attempt += 1;
      if (attempt > CATCH_UP_MAX_RETRIES) throw err;
      await sleep(delayMs);
      delayMs = Math.min(delayMs * CATCH_UP_BACKOFF_MULTIPLIER, CATCH_UP_MAX_BACKOFF_MS);
    }
  }
}

/** Writes a hint-triggered catch-up batch into the base query's cache entry: dedups by
 * `rowKey()` and prepends (the batch arrives id-ASC; existing entries are id-DESC, and every
 * fetched record is newer than everything already cached). Detects DB `id` regression (backup
 * restore / telemetry wipe): if the batch's max `id` is below the cache's current max, the cached
 * history predates the reset and is discarded in favor of a fresh start from this batch, with a
 * one-time notice surfaced so the gap is visible rather than a silent indefinite stall. The merged
 * result is trimmed to `MAX_CACHED_LOG_ENTRIES` (keeping the most recent rows, since the array
 * stays id-DESC throughout) so the cache doesn't grow without bound over a long-lived mount. */
function mergeCatchUpBatch(queryClient: QueryClient, scopedKey: readonly unknown[], results: LogEntry[]): void {
  queryClient.setQueryData<LogEntry[]>(scopedKey, (old) => {
    const existing = old ?? [];
    if (results.length === 0) return existing;

    if (existing.length > 0 && maxId(results) < maxId(existing)) {
      toast.error("Log stream reset — the server's log history was reset.");
      return [...results].reverse().slice(0, MAX_CACHED_LOG_ENTRIES);
    }

    const seen = new Set(existing.map(rowKey));
    const fresh: LogEntry[] = [];
    for (const entry of results) {
      const key = rowKey(entry);
      if (seen.has(key)) continue;
      seen.add(key);
      fresh.push(entry);
    }
    return [...fresh.reverse(), ...existing].slice(0, MAX_CACHED_LOG_ENTRIES);
  });
}

/** Runs one catch-up episode: fetch from the cache's current cursor, merge, and — if the page was
 * full — repeat with the advanced cursor, up to `CATCH_UP_MAX_PAGES` consecutive full pages. */
async function performCatchUp(queryClient: QueryClient, context: CatchUpContext): Promise<void> {
  const { scopedKey, appKey, executionId, since } = context;
  let consecutiveFullPages = 0;
  let isFirstFetch = true;

  while (consecutiveFullPages < CATCH_UP_MAX_PAGES) {
    if (!isFirstFetch) await sleep(CATCH_UP_MIN_DELAY_MS);
    isFirstFetch = false;

    const cached = queryClient.getQueryData<LogEntry[]>(scopedKey) ?? [];
    const sinceId = maxId(cached);

    let results: LogEntry[];
    try {
      results = await fetchSinceWithBackoff(queryClient, scopedKey, sinceId, { appKey, executionId, since });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to fetch recent logs");
      return;
    }

    if (results.length === 0) return;

    mergeCatchUpBatch(queryClient, scopedKey, results);

    if (results.length < REST_FETCH_LIMIT) return;

    consecutiveFullPages += 1;
  }
}

export function useLogData({ appKey, executionId }: UseLogDataParams): UseLogDataResult {
  const queryClient = useQueryClient();

  const logHintVersion = useAppStore((s) => s.logHintVersion);
  const timePreset = useAppStore((s) => s.timePreset);
  const urlWindowParam = useAppStore((s) => s.urlWindowParam);
  const uptimeSeconds = useAppStore((s) => s.uptimeSeconds);

  const preset = urlWindowParam ?? timePreset;
  const since = resolveSince(preset, uptimeSeconds) ?? 0;
  const waitingForUptime = preset === "since-restart" && uptimeSeconds === null;

  // Mirrors useScopedQuery's own queryKey computation (see that hook's docstring) — both hooks
  // read preset/uptimeSeconds from the same store, so the keys always agree, and hint-triggered
  // writes via setQueryData land in the exact cache entry the base query below owns.
  const scopedKey = useMemo(
    () =>
      [
        ...queryKeys.recentLogs(appKey, executionId),
        preset,
        ...(preset === "since-restart" ? [uptimeSeconds] : []),
      ] as const,
    [appKey, executionId, preset, uptimeSeconds],
  );

  const { data, isPending, isError, error } = useScopedQuery(queryKeys.recentLogs(appKey, executionId), (s, signal) =>
    getRecentLogs({ appKey, limit: REST_FETCH_LIMIT, executionId, since: s }, signal),
  );

  useEffect(() => {
    if (isError && error) {
      toast.error(error instanceof Error ? error.message : "Failed to load recent logs");
    }
  }, [isError, error]);

  // Mirrored into a ref on every render so the debounced/async catch-up flow always reads the
  // latest filters/key instead of a closure captured at the moment the hint arrived.
  const contextRef = useRef<CatchUpContext>({ scopedKey, appKey, executionId, since, waitingForUptime });
  contextRef.current = { scopedKey, appKey, executionId, since, waitingForUptime };

  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxWaitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevHintVersionRef = useRef(logHintVersion);

  // Serializes performCatchUp runs so a newly-scheduled run never executes concurrently with one
  // already in flight — each run chains onto the prior run's promise instead of racing it. Without
  // this, two overlapping runs can each snapshot `sinceId` at a different time; the slower run's
  // (now-stale) results can have a lower max id than the cache's current (already-advanced) max,
  // which mergeCatchUpBatch's reset-detection misreads as a genuine backend DB reset. Chaining
  // (rather than skipping a run while one is active) means every hint-driven window still gets
  // its own catch-up fetch, just deferred until the prior one settles — no coverage gap. The chain
  // promise always resolves (performCatchUp catches its own fetch errors internally), but `.catch`
  // here is defensive so an unexpected throw can never permanently wedge the chain.
  const catchUpChainRef = useRef<Promise<void>>(Promise.resolve());

  useEffect(
    () => () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      if (maxWaitTimerRef.current) clearTimeout(maxWaitTimerRef.current);
    },
    [],
  );

  useEffect(() => {
    // Skip on mount (and on any render where the version didn't actually change) — a newly
    // mounted view's base query above already fetches fresh, so it needs no catch-up.
    if (logHintVersion === prevHintVersionRef.current) return;
    prevHintVersionRef.current = logHintVersion;
    if (contextRef.current.waitingForUptime) return; // base query isn't fetching yet either

    const runCatchUp = () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
      if (maxWaitTimerRef.current) {
        clearTimeout(maxWaitTimerRef.current);
        maxWaitTimerRef.current = null;
      }
      const context = contextRef.current;
      catchUpChainRef.current = catchUpChainRef.current
        .catch(() => {})
        .then(() => performCatchUp(queryClient, context));
    };

    if (!maxWaitTimerRef.current) {
      maxWaitTimerRef.current = setTimeout(runCatchUp, HINT_MAX_WAIT_MS);
    }
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(runCatchUp, HINT_DEBOUNCE_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- queryClient is stable; contextRef carries the rest
  }, [logHintVersion]);

  const restEntries = useMemo<LogEntry[]>(() => data ?? [], [data]);

  return { allEntries: restEntries, restEntries, loading: isPending };
}
