import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";

import { ApiError } from "@/api/client";
import { getLogsSince, getRecentLogs, type LogEntry } from "@/api/endpoints";
import { useScopedQuery } from "@/hooks/use-scoped-query";
import { queryKeys } from "@/lib/query-keys";
import { useAppStore } from "@/state/store";
import { resolveSince } from "@/utils/time-window";

import { CATCH_UP_FETCH_LIMIT, MAX_CACHED_LOG_ENTRIES, REST_FETCH_LIMIT } from "./constants";
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

// Independent fallback for the "hint arrives before DB write completes" race (design.md's
// documented edge case): the hint that would have triggered a retry only exists if more logging
// happens afterward. If a burst's last record loses that race and the app then goes quiet, no
// further hint ever arrives to pick it up — the UI silently stalls until an unrelated future log
// line happens to sweep it in. This periodic re-sync runs regardless of hint activity so that
// window is always bounded, independent of whether logging continues.
const PERIODIC_RESYNC_MS = 5000;

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
  isWaitingForUptime: boolean;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function maxId(entries: readonly LogEntry[]): number {
  return entries.length ? Math.max(...entries.map((e) => e.id)) : 0;
}

/** A 4xx response means the request itself is malformed — retrying the identical request can
 * never succeed, so it's treated as permanent rather than transient. */
function isClientError(err: unknown): boolean {
  return err instanceof ApiError && err.status >= 400 && err.status < 500;
}

/** Thrown internally to unwind the retry loop and `performCatchUp`'s page loop once `signal` fires
 * — a plain, checkable sentinel distinct from a real fetch failure, so callers can tell "cancelled"
 * apart from "failed" without inspecting `DOMException` details. */
class CatchUpAbortedError extends Error {}

/** Fetches one page from `GET /logs/since/{sinceId}` via `queryClient.fetchQuery`, so TanStack's
 * error-state propagation applies. Retries on failure with the backoff shape described above,
 * except for a 4xx response (`isClientError`), which fails immediately since retrying an
 * identical malformed request can never succeed. A distinct `queryKey` per attempt keeps this
 * fetch out of the base query's cache entry — the caller merges the successful result into that
 * entry explicitly.
 *
 * `signal` is checked between attempts and around each backoff sleep — it doesn't abort a request
 * already in flight (see `performCatchUp`'s docstring), but it stops the retry loop from starting
 * another attempt or sleeping through a full backoff window once the caller's context (unmount, or
 * a filter change swapping `scopedKey`) is gone. */
async function fetchSinceWithBackoff(
  queryClient: QueryClient,
  scopedKey: readonly unknown[],
  sinceId: number,
  filters: CatchUpFilters,
  signal: AbortSignal,
): Promise<LogEntry[]> {
  let attempt = 0;
  let delayMs = CATCH_UP_INITIAL_BACKOFF_MS;

  while (true) {
    if (signal.aborted) throw new CatchUpAbortedError();
    try {
      return await queryClient.fetchQuery<LogEntry[]>({
        queryKey: [...scopedKey, "since", sinceId, attempt],
        queryFn: ({ signal: fetchSignal }) =>
          getLogsSince(sinceId, { ...filters, limit: CATCH_UP_FETCH_LIMIT }, fetchSignal),
        staleTime: 0,
        gcTime: 0,
        retry: false,
      });
    } catch (err) {
      if (isClientError(err)) throw err;
      attempt += 1;
      if (attempt > CATCH_UP_MAX_RETRIES) throw err;
      await sleep(delayMs);
      if (signal.aborted) throw new CatchUpAbortedError();
      delayMs = Math.min(delayMs * CATCH_UP_BACKOFF_MULTIPLIER, CATCH_UP_MAX_BACKOFF_MS);
    }
  }
}

/** Writes a batch of freshly-fetched `LogEntry` results into the base query's cache entry via a
 * dedup+union merge (keyed by `rowKey()`), re-sorted by `id` descending — the DB's monotonic
 * auto-incrementing primary key (design.md FR#10) — and trimmed to `MAX_CACHED_LOG_ENTRIES` so the
 * cache doesn't grow without bound over a long-lived mount.
 *
 * Deliberately order-agnostic: this is the single write path for both of the cache's producers —
 * hint-triggered catch-up (`/logs/since`, id-ASC, every record newer than what's cached) and the
 * base query's own refresh (`/logs/recent`, latest-N DESC, which can overlap arbitrarily with
 * what's already cached) — sharing one function is what makes the base query's refresh a merge
 * instead of `useQuery`'s default full-replace, closing the race where a WS reconnect or
 * preset/filter change's base-query refetch could otherwise silently overwrite entries a
 * concurrent or just-completed catch-up had already merged in.
 *
 * Detects DB `id` regression (backup restore / telemetry wipe) from either producer: if the
 * incoming batch's max `id` is below the cache's current max, the cached history predates the
 * reset and is discarded in favor of a fresh start from this batch, with a one-time notice
 * surfaced — this guard now protects the base-query refresh path too, not just catch-up, since
 * without it stale pre-reset rows would silently outrank genuinely fresher post-reset rows by id
 * forever. */
function mergeCatchUpBatch(queryClient: QueryClient, scopedKey: readonly unknown[], results: LogEntry[]): void {
  queryClient.setQueryData<LogEntry[]>(scopedKey, (old) => {
    const existing = old ?? [];
    if (results.length === 0) return existing;

    if (existing.length > 0 && maxId(results) < maxId(existing)) {
      toast.error("Log stream reset — the server's log history was reset.");
      return [...results].sort((a, b) => b.id - a.id).slice(0, MAX_CACHED_LOG_ENTRIES);
    }

    const seen = new Set(existing.map(rowKey));
    const fresh: LogEntry[] = [];
    for (const entry of results) {
      const key = rowKey(entry);
      if (seen.has(key)) continue;
      seen.add(key);
      fresh.push(entry);
    }
    return [...fresh, ...existing].sort((a, b) => b.id - a.id).slice(0, MAX_CACHED_LOG_ENTRIES);
  });
}

/** Runs one catch-up episode: fetch from the cache's current cursor, merge, and — if the page was
 * full — repeat with the advanced cursor, up to `CATCH_UP_MAX_PAGES` consecutive full pages.
 *
 * A 4xx (`isClientError`) failure is permanent — retrying the identical request on the next
 * hint-triggered episode can never succeed either, so `permanentFailureKeyRef` gates the toast to
 * once per catch-up chain lifetime instead of once per episode. The ref holds the `scopedKey` that
 * failed; comparing by reference means it self-resets on a filter change (a new `scopedKey` from
 * the hook's `useMemo`) without any extra bookkeeping, and a later successful fetch clears it
 * explicitly. Permanent failures always toast, regardless of `isBackgroundPoll` — silencing those
 * would let the periodic poll (below) permanently hide a real broken contract, since it's often the
 * *only* trigger running during a quiet period. `isBackgroundPoll` only silences the transient
 * (non-4xx) failure path, which has no such gate and would otherwise toast on every poll tick
 * during a sustained outage; a hint-triggered attempt still surfaces those normally.
 *
 * `signal` is aborted by the hook on unmount or on a filter change (a new `scopedKey`) — checked
 * before each page and threaded into `fetchSinceWithBackoff` so a stranded episode stops scheduling
 * further pages/retries instead of running to completion (up to 5 pages, each with retries/backoff
 * up to 30s) against a view that's already gone. It does not cancel a request already in flight;
 * that request's result is simply discarded (`CatchUpAbortedError`, silent — cancellation isn't a
 * failure worth a toast). */
async function performCatchUp(
  queryClient: QueryClient,
  context: CatchUpContext,
  permanentFailureKeyRef: { current: readonly unknown[] | null },
  isBackgroundPoll: boolean,
  signal: AbortSignal,
): Promise<void> {
  const { scopedKey, appKey, executionId, since } = context;
  let consecutiveFullPages = 0;
  let isFirstFetch = true;

  while (consecutiveFullPages < CATCH_UP_MAX_PAGES) {
    if (signal.aborted) return;
    if (!isFirstFetch) await sleep(CATCH_UP_MIN_DELAY_MS);
    isFirstFetch = false;
    if (signal.aborted) return;

    const cached = queryClient.getQueryData<LogEntry[]>(scopedKey) ?? [];
    const sinceId = maxId(cached);

    let results: LogEntry[];
    try {
      results = await fetchSinceWithBackoff(queryClient, scopedKey, sinceId, { appKey, executionId, since }, signal);
    } catch (err) {
      if (err instanceof CatchUpAbortedError) return;
      if (isClientError(err)) {
        if (permanentFailureKeyRef.current !== scopedKey) {
          permanentFailureKeyRef.current = scopedKey;
          toast.error(err instanceof Error ? err.message : "Failed to fetch recent logs");
        }
        return;
      }
      if (!isBackgroundPoll) toast.error(err instanceof Error ? err.message : "Failed to fetch recent logs");
      return;
    }
    if (signal.aborted) return;
    permanentFailureKeyRef.current = null;

    if (results.length === 0) return;

    mergeCatchUpBatch(queryClient, scopedKey, results);

    if (results.length < CATCH_UP_FETCH_LIMIT) return;

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
  const isWaitingForUptime = preset === "since-restart" && uptimeSeconds === null;

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

  // Merges through mergeCatchUpBatch instead of returning the fresh page directly, so a refetch
  // (WS reconnect, preset/filter change) never wholesale-replaces entries a concurrent or
  // just-completed hint-triggered catch-up already merged in — see that function's docstring.
  // mergeCatchUpBatch writes the merge result into the cache itself; returning it here as well
  // just makes useScopedQuery's own post-resolution cache write a no-op (same value, redundant set)
  // instead of a second, conflicting write.
  const { data, isPending, isError, error } = useScopedQuery<LogEntry[]>(
    queryKeys.recentLogs(appKey, executionId),
    async (s, signal) => {
      const fresh = await getRecentLogs({ appKey, limit: REST_FETCH_LIMIT, executionId, since: s }, signal);
      mergeCatchUpBatch(queryClient, scopedKey, fresh);
      return queryClient.getQueryData<LogEntry[]>(scopedKey) ?? fresh;
    },
  );

  useEffect(() => {
    if (isError && error) {
      toast.error(error instanceof Error ? error.message : "Failed to load recent logs");
    }
  }, [isError, error]);

  // Mirrored into a ref on every render so the debounced/async catch-up flow always reads the
  // latest filters/key instead of a closure captured at the moment the hint arrived.
  const contextRef = useRef<CatchUpContext>({ scopedKey, appKey, executionId, since, isWaitingForUptime });
  contextRef.current = { scopedKey, appKey, executionId, since, isWaitingForUptime };

  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxWaitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevHintVersionRef = useRef(logHintVersion);

  // Which scopedKey (if any) last hit a permanent (4xx) catch-up failure — see performCatchUp's
  // docstring for how this gates the repeat-toast.
  const permanentFailureKeyRef = useRef<readonly unknown[] | null>(null);

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

  // Aborted (and replaced) whenever scopedKey changes, and aborted on unmount — see
  // performCatchUp's docstring for what this stops. Read via `.current.signal` inside each
  // scheduled run rather than captured at schedule time, so a run that hasn't started executing
  // yet always sees the controller current at execution time, not at scheduling time.
  const abortControllerRef = useRef<AbortController>(new AbortController());

  useEffect(
    () => () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      if (maxWaitTimerRef.current) clearTimeout(maxWaitTimerRef.current);
    },
    [],
  );

  useEffect(() => {
    abortControllerRef.current = new AbortController();
    return () => abortControllerRef.current.abort();
  }, [scopedKey]);

  // Bounded fallback re-sync — see PERIODIC_RESYNC_MS's docstring. Independent of hints entirely,
  // so it still chains through catchUpChainRef (serializing against any concurrent hint-triggered
  // run) but bypasses the debounce/maxWait timers, which exist only to coalesce bursty hints.
  useEffect(() => {
    const interval = setInterval(() => {
      if (contextRef.current.isWaitingForUptime) return;
      const context = contextRef.current;
      catchUpChainRef.current = catchUpChainRef.current
        .catch(() => {})
        .then(() =>
          performCatchUp(queryClient, context, permanentFailureKeyRef, true, abortControllerRef.current.signal),
        );
    }, PERIODIC_RESYNC_MS);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- queryClient is stable; refs read fresh values each tick
  }, []);

  useEffect(() => {
    // Skip on mount (and on any render where the version didn't actually change) — a newly
    // mounted view's base query above already fetches fresh, so it needs no catch-up.
    if (logHintVersion === prevHintVersionRef.current) return;
    prevHintVersionRef.current = logHintVersion;
    if (contextRef.current.isWaitingForUptime) return; // base query isn't fetching yet either

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
        .then(() =>
          performCatchUp(queryClient, context, permanentFailureKeyRef, false, abortControllerRef.current.signal),
        );
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
