import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";

import { ApiError } from "@/api/client";
import { getLogsSince, getRecentLogs, type LogEntry } from "@/api/endpoints";
import { useScopedQuery } from "@/hooks/use-scoped-query";
import { queryKeys } from "@/lib/query-keys";
import { useAppStore } from "@/state/store";
import { resolveSince } from "@/utils/time-window";

import { CATCH_UP_FETCH_LIMIT, MAX_CACHED_LOG_ENTRIES, RESET_PROBE_LIMIT, REST_FETCH_LIMIT } from "./constants";
import { rowKey } from "./types";

interface UseLogDataParams {
  appKey?: string;
  executionId?: string | null;
}

interface UseLogDataResult {
  /** The live, continuously-merged entry cache — base-query results plus every hint-triggered
   * catch-up merge. `useLogFilters` is responsible for freezing its own snapshot of this when
   * the user pauses live updates (e.g. by sorting); this hook has only one data source to give
   * it. */
  allEntries: LogEntry[];
  loading: boolean;
}

// Timing constants below are `export`ed only when use-log-data.test.ts needs to reference them
// (to derive fake-timer advances instead of hardcoding milliseconds); constants with no test
// consumer stay module-private.

// Debounce-with-maxWait for coalescing bursty `log_hint` messages into one REST fetch. Each hint
// resets the debounce timer; maxWait guarantees a fetch fires at least this often even under a
// continuous burst, so the table isn't silenced for the whole burst duration.
export const HINT_DEBOUNCE_MS = 200;
export const HINT_MAX_WAIT_MS = 500;

// Bounds for the catch-up loop that follows a full-page response — a full page means there may
// be more records beyond the page just fetched.
export const CATCH_UP_MAX_PAGES = 5;
export const CATCH_UP_MIN_DELAY_MS = 100;

// Independent fallback for the "hint arrives before DB write completes" race (design.md's
// documented edge case): the hint that would have triggered a retry only exists if more logging
// happens afterward. If a burst's last record loses that race and the app then goes quiet, no
// further hint ever arrives to pick it up — the UI silently stalls until an unrelated future log
// line happens to sweep it in. This periodic re-sync runs regardless of hint activity so that
// window is always bounded, independent of whether logging continues.
export const PERIODIC_RESYNC_MS = 5000;

// Mirrors the WS reconnect backoff constants in use-websocket.ts (INITIAL_BACKOFF_MS=1000,
// MAX_BACKOFF_MS=30000, BACKOFF_MULTIPLIER=1.5) — same shape, applied to catch-up fetch retries on
// non-2xx responses instead of WS reconnect attempts. Not imported directly: those constants are
// module-local to use-websocket.ts.
export const CATCH_UP_INITIAL_BACKOFF_MS = 1000;
const CATCH_UP_MAX_BACKOFF_MS = 30_000;
export const CATCH_UP_BACKOFF_MULTIPLIER = 1.5;
export const CATCH_UP_MAX_RETRIES = 3;

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

/** Tracks the true monotonic high-water-mark id per `scopedKey`, independently of the trimmed,
 * timestamp-sorted display cache — see `mergeCatchUpBatch`'s docstring for why the two can't
 * share one number. Deliberately not a `queryClient` cache entry: nothing ever mounts a `useQuery`
 * observer for this value, and an unobserved entry is eligible for GC after `gcTime` (as low as 0
 * in tests, `DEFAULT_GC_TIME_MS` in production) — silently resetting the cursor to 0 mid-session.
 * Keyed by `QueryClient` instance (one per app session; a fresh one per test) so cursor state
 * can't leak between an app's lifetime and the next, or between tests. */
const highWaterMarks = new WeakMap<QueryClient, Map<string, number>>();

function cursorMapFor(queryClient: QueryClient): Map<string, number> {
  let map = highWaterMarks.get(queryClient);
  if (!map) {
    map = new Map();
    highWaterMarks.set(queryClient, map);
  }
  return map;
}

// Single source of truth for turning a scopedKey into a Map key — every cursor helper below
// goes through this instead of calling JSON.stringify(scopedKey) itself, so a future change to
// how scopedKey is serialized (e.g. if it ever gains a member JSON.stringify can't represent
// deterministically) only has one call site to update.
function cursorMapKey(scopedKey: readonly unknown[]): string {
  return JSON.stringify(scopedKey);
}

function getCursor(queryClient: QueryClient, scopedKey: readonly unknown[]): number {
  return cursorMapFor(queryClient).get(cursorMapKey(scopedKey)) ?? 0;
}

function advanceCursor(queryClient: QueryClient, scopedKey: readonly unknown[], batchMaxId: number): void {
  const map = cursorMapFor(queryClient);
  const key = cursorMapKey(scopedKey);
  if (batchMaxId > (map.get(key) ?? 0)) map.set(key, batchMaxId);
}

function resetCursor(queryClient: QueryClient, scopedKey: readonly unknown[], value: number): void {
  cursorMapFor(queryClient).set(cursorMapKey(scopedKey), value);
}

/** Carries catch-up state from one `scopedKey` to another when only the key's trailing
 * `uptimeSeconds` component changed — see the since-restart migration block in `useLogData` for
 * when this fires and why. Copies the high-water-mark cursor (only forward, via `advanceCursor`'s
 * own `Math.max`) and, if the new key has no cached entries yet, the old key's merged cache too —
 * so the new key starts exactly where the old one left off instead of from an empty slate. */
function migrateCursorAndCache(queryClient: QueryClient, oldKey: readonly unknown[], newKey: readonly unknown[]): void {
  const oldCursor = getCursor(queryClient, oldKey);
  if (oldCursor > 0) advanceCursor(queryClient, newKey, oldCursor);

  const oldEntries = queryClient.getQueryData<LogEntry[]>(oldKey);
  if (oldEntries && oldEntries.length > 0 && queryClient.getQueryData<LogEntry[]>(newKey) === undefined) {
    queryClient.setQueryData<LogEntry[]>(newKey, oldEntries);
  }
}

/** Matches the backend's own canonical display ordering for `get_log_records` (design.md FR#10:
 * `timestamp DESC, seq DESC`) — `id` is reserved for the catch-up cursor (`maxId`, monotonic and
 * restart-safe) and is not used for display order, since DB insertion order (`id`) and event
 * timestamp order can diverge under concurrent inserts or clock skew. `filterLogEntries`'s
 * `keepTimestampSourceOrder` fast path depends on the merged cache genuinely holding this order. */
function byTimestampDesc(a: LogEntry, b: LogEntry): number {
  return b.timestamp - a.timestamp || b.seq - a.seq;
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
 * dedup+union merge (keyed by `rowKey()`), re-sorted via `byTimestampDesc` — matching the
 * backend's own canonical display order (design.md FR#10: `timestamp DESC, seq DESC`) — and
 * trimmed to `MAX_CACHED_LOG_ENTRIES` so the cache doesn't grow without bound over a long-lived
 * mount.
 *
 * Also advances a separate, untrimmed high-water-mark cursor (`advanceCursor`/`getCursor`) to the batch's max
 * `id` — this can't be recovered from the display cache alone: a record with the highest id ever
 * seen but an older timestamp (concurrent inserts, clock skew/rollback) sorts toward the bottom
 * and can be immediately trimmed out once the cache is full, and `performCatchUp` computing its
 * `sinceId` from that trimmed array would then re-fetch and re-discard the same record forever,
 * stalling the live table. The cursor only ever moves forward on a normal merge (`Math.max` with
 * whatever's already recorded) and is hard-reset (not maxed) on a detected reset below, since the
 * pre-reset cursor is no longer meaningful once the history it pointed into has been discarded.
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
 * incoming batch's max `id` is below the tracked cursor (not the trimmed display cache's own max
 * — the cursor-owning row can have aged out of the timestamp-sorted cache while the cursor itself
 * survives, so comparing against the display cache's max can miss a real regression that still
 * lands below the cursor), the cached history predates the reset and is discarded in favor of a
 * fresh start from this batch, with a one-time notice surfaced — this guard now protects the
 * base-query refresh path too, not just catch-up, since without it stale pre-reset rows would
 * silently outrank genuinely fresher post-reset rows by id forever.
 *
 * `detectReset` gates that check and has no default — every call site states its intent
 * explicitly, since silently inheriting the wrong one for a future call site would misfire the
 * check below. `true` for catch-up (`performCatchUp`) and the reset probe (`probeForReset`), both
 * of which fetch strictly relative to a cursor and so a lower max really does mean the DB reset.
 * The base query's own `/logs/recent` refresh is a plain recency snapshot with no such
 * relationship to the cache's current cursor — if it starts before a catch-up run but resolves
 * after that run already advanced the cache, its own (now-stale) max id can be lower than the
 * cache's current max for a completely ordinary reason, which the reset-detection heuristic can't
 * tell apart from a real reset. The base query's call site passes `detectReset: false` for
 * exactly this reason; a real reset is still caught via the catch-up/probe path shortly after (an
 * empty `/logs/since` against the old, too-high cursor triggers `probeForReset`, which detects it
 * there instead).
 *
 * `windowSince`, when given, drops `existing` entries whose `timestamp` has fallen before it —
 * the base-query refresh path's only mechanism for evicting rows that have aged out of a fixed
 * (1h/24h/7d) time window, since `since` slides forward on every refresh but the count-based
 * `MAX_CACHED_LOG_ENTRIES` trim alone won't evict a quiet, under-cap cache. Deliberately never
 * applied to `results`/`fresh`: the server already filtered that batch by the same boundary, so
 * re-filtering it here is redundant in production and actively wrong in tests, whose fixtures use
 * arbitrary fixed timestamps unrelated to wall-clock time — filtering fresh results would prune
 * them outright regardless of `since`. Omit `windowSince` entirely for catch-up and the reset
 * probe, which are cursor-relative rather than window-relative and would otherwise prune records
 * the current window boundary was never meant to bound. */
interface MergeOptions {
  detectReset: boolean;
  windowSince?: number;
}

function mergeCatchUpBatch(
  queryClient: QueryClient,
  scopedKey: readonly unknown[],
  results: LogEntry[],
  { detectReset, windowSince }: MergeOptions,
): void {
  if (results.length === 0) {
    // Nothing to merge, dedupe, or reset-check — but a fixed-window refresh (windowSince set)
    // still needs to evict cache entries that aged out of the window while the stream was quiet.
    // Without this, a batch-empty refetch would otherwise skip pruning entirely and leave expired
    // rows visible indefinitely (see `windowSince`'s docstring above).
    if (windowSince !== undefined) {
      queryClient.setQueryData<LogEntry[]>(scopedKey, (old) => (old ?? []).filter((e) => e.timestamp >= windowSince));
    }
    return;
  }
  const batchMaxId = maxId(results);

  queryClient.setQueryData<LogEntry[]>(scopedKey, (old) => {
    const existing = old ?? [];
    const trackedCursor = getCursor(queryClient, scopedKey);

    if (detectReset && existing.length > 0 && batchMaxId < trackedCursor) {
      toast.error("Log stream reset — the server's log history was reset.");
      resetCursor(queryClient, scopedKey, batchMaxId);
      return [...results].sort(byTimestampDesc).slice(0, MAX_CACHED_LOG_ENTRIES);
    }

    advanceCursor(queryClient, scopedKey, batchMaxId);

    const seen = new Set(existing.map(rowKey));
    const fresh: LogEntry[] = [];
    for (const entry of results) {
      const key = rowKey(entry);
      if (seen.has(key)) continue;
      seen.add(key);
      fresh.push(entry);
    }
    // Only ever prunes `existing` — never `fresh`, which the server already filtered by the same
    // boundary. Filtering `fresh` too would be redundant in production and wrong in tests (see
    // `windowSince`'s docstring above for why).
    const survivingExisting = windowSince === undefined ? existing : existing.filter((e) => e.timestamp >= windowSince);
    return [...fresh, ...survivingExisting].sort(byTimestampDesc).slice(0, MAX_CACHED_LOG_ENTRIES);
  });
}

/** After an empty `/logs/since` page — which can mean either "nothing new" or "the DB was reset
 * and this cursor now exceeds every id in it" (the endpoint's `id > since_id` filter returns
 * empty either way, so it can never distinguish the two on its own) — probes `/logs/recent` for
 * the `RESET_PROBE_LIMIT` most-recent-by-timestamp records and merges them through
 * `mergeCatchUpBatch`, which already knows how to detect and recover from a reset via its own
 * max-id comparison over the whole batch. Fetching a batch rather than a single row matters here:
 * `/logs/recent` orders by timestamp, not id (see `RESET_PROBE_LIMIT`'s docstring), so a single
 * row's id can understate the true current max under clock skew/concurrent inserts and misfire a
 * false reset. A quiet stream just re-merges its own already-cached tail (deduped, so a no-op); a
 * reset surfaces the standard "Log stream reset" notice and discards the stale cache, unblocking
 * every subsequent catch-up fetch. Best-effort: a failed probe defers the check to the next tick
 * rather than blocking or toasting on its own — the caller has already returned by the time this
 * settles. */
async function probeForReset(
  queryClient: QueryClient,
  scopedKey: readonly unknown[],
  context: CatchUpContext,
  signal: AbortSignal,
): Promise<void> {
  const { appKey, executionId, since } = context;
  try {
    const latest = await queryClient.fetchQuery<LogEntry[]>({
      queryKey: [...scopedKey, "reset-probe"],
      queryFn: ({ signal: fetchSignal }) =>
        getRecentLogs({ appKey, executionId, since, limit: RESET_PROBE_LIMIT }, fetchSignal),
      staleTime: 0,
      gcTime: 0,
      retry: false,
    });
    if (signal.aborted) return;
    // detectReset: true — this probe exists specifically to detect a reset.
    mergeCatchUpBatch(queryClient, scopedKey, latest, { detectReset: true });
  } catch {
    // Best-effort — see docstring above.
  }
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

    // Read from the untrimmed cursor, not maxId(displayCache) — see mergeCatchUpBatch's
    // docstring for why the display cache alone can't be trusted for this.
    const sinceId = getCursor(queryClient, scopedKey);

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

    if (results.length === 0) {
      // sinceId > 0 means there's a cursor a reset could actually invalidate — an empty cache
      // has nothing to protect, so skip the extra request.
      if (sinceId > 0) await probeForReset(queryClient, scopedKey, context, signal);
      return;
    }

    // detectReset: true — a cursor-based fetch, so a lower max really is a reset.
    mergeCatchUpBatch(queryClient, scopedKey, results, { detectReset: true });

    if (results.length < CATCH_UP_FETCH_LIMIT) return;

    consecutiveFullPages += 1;
  }
}

/** Owns the hint-triggered and periodic catch-up scheduling for `useLogData`: the debounce/maxWait
 * coalescing of `log_hint` events, the bounded periodic re-sync, and the abort/serialization
 * plumbing (`catchUpChainRef`, `abortControllerRef`) that both share. Pulled out of `useLogData`
 * itself purely to keep the base-query setup and the catch-up scheduling readable as separate
 * concerns — every ref, effect body, and dependency array here is unchanged from before the split. */
function useCatchUpScheduler(
  queryClient: QueryClient,
  {
    scopedKey,
    appKey,
    executionId,
    since,
    isWaitingForUptime,
    logHintVersion,
  }: CatchUpContext & { logHintVersion: number },
): void {
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
  // performCatchUp's docstring for what this stops. Captured together with `context` at
  // schedule time (both read from refs at the same synchronous instant), never separately —
  // a run queued behind an in-flight one in `catchUpChainRef` doesn't execute until the prior
  // link resolves, and if scope changed in that gap, reading `.current.signal` lazily inside the
  // `.then()` would pair a stale `context` (old scope) with the *new* scope's live, un-aborted
  // signal. That mismatched run would never observe its own scope's abort, so it keeps fetching
  // and retrying against a scope nobody's viewing anymore, blocking the new scope's own queued
  // run behind it. Pairing both at schedule time means a stale run always carries its own
  // scope's (already-aborted) signal and bails via `if (signal.aborted) return` like it should.
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
      const signal = abortControllerRef.current.signal;
      catchUpChainRef.current = catchUpChainRef.current
        .catch(() => {})
        .then(() => performCatchUp(queryClient, context, permanentFailureKeyRef, true, signal));
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
      const signal = abortControllerRef.current.signal;
      catchUpChainRef.current = catchUpChainRef.current
        .catch(() => {})
        .then(() => performCatchUp(queryClient, context, permanentFailureKeyRef, false, signal));
    };

    if (!maxWaitTimerRef.current) {
      maxWaitTimerRef.current = setTimeout(runCatchUp, HINT_MAX_WAIT_MS);
    }
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(runCatchUp, HINT_DEBOUNCE_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- queryClient is stable; contextRef carries the rest
  }, [logHintVersion]);
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

  // Identifies "the same logical view" independent of uptime — used below to detect a since-
  // restart reconnect (identity unchanged, only uptime moved) as distinct from an actual scope
  // change (app/execution/preset switched).
  const identityKey = useMemo(
    () => [...queryKeys.recentLogs(appKey, executionId), preset] as const,
    [appKey, executionId, preset],
  );

  // Mirrors useScopedQuery's own queryKey computation (see that hook's docstring) — both hooks
  // read preset/uptimeSeconds from the same store, so the keys always agree, and hint-triggered
  // writes via setQueryData land in the exact cache entry the base query below owns.
  const scopedKey = useMemo(
    () => [...identityKey, ...(preset === "since-restart" ? [uptimeSeconds] : [])] as const,
    [identityKey, preset, uptimeSeconds],
  );

  // `uptimeSeconds` updates on every WS reconnect (handleWsConnected in store.ts), not only on a
  // genuine server restart — so for the since-restart preset, a plain reconnect changes scopedKey
  // and would otherwise abandon the catch-up cursor and merged cache built up under the previous
  // key, silently dropping a gap of up to (records-since-old-cursor minus REST_FETCH_LIMIT) rows.
  // Runs during render (before useScopedQuery/useCatchUpScheduler below ever read the new key) so
  // the migrated state is in place before anything fetches against it. Only fires when the
  // identity (app/execution/preset) is unchanged — an actual scope change is a real reset of
  // context, not a reconnect, and gets a fresh cursor/cache on purpose. A genuine server restart
  // is still caught independently by mergeCatchUpBatch's own id-regression check on the next
  // merge; this migration only prevents an ordinary reconnect from being mistaken for one.
  //
  // Mutating the query cache directly in the render body (rather than a useEffect) is a
  // deliberate exception to the usual side-effects-in-effects rule: an effect would run one
  // render too late, after useScopedQuery/useCatchUpScheduler below have already read the new
  // (unmigrated) key for this render, producing a visible loading flash. The `prevScopedKeyRef`
  // reference-equality guard makes this idempotent across a StrictMode double-render (the second
  // invocation always sees `prevScopedKeyRef.current === scopedKey`, since the first invocation
  // already advanced the ref), so this can't double-migrate.
  const prevIdentityKeyRef = useRef<readonly unknown[] | null>(null);
  const prevScopedKeyRef = useRef<readonly unknown[] | null>(null);
  if (
    // Both refs are plain reference checks — identityKey and scopedKey are both useMemo'd, so
    // either one's reference is stable across renders where its own deps didn't change. scopedKey
    // must differ (something changed) while identityKey must not (that something was only
    // uptime) for this to be an uptime-only reconnect rather than a real scope change.
    preset === "since-restart" &&
    prevScopedKeyRef.current !== null &&
    prevScopedKeyRef.current !== scopedKey &&
    prevIdentityKeyRef.current === identityKey
  ) {
    migrateCursorAndCache(queryClient, prevScopedKeyRef.current, scopedKey);
  }
  prevIdentityKeyRef.current = identityKey;
  prevScopedKeyRef.current = scopedKey;

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
      // detectReset: false — a plain recency snapshot with no cursor relationship to the cache's
      // current max id; see mergeCatchUpBatch's docstring for the race this avoids.
      // windowSince: only for fixed-window presets — since-restart's boundary is the whole
      // post-boot history and isn't meant to prune anything as time passes.
      mergeCatchUpBatch(queryClient, scopedKey, fresh, {
        detectReset: false,
        windowSince: preset === "since-restart" ? undefined : s,
      });
      return queryClient.getQueryData<LogEntry[]>(scopedKey) ?? fresh;
    },
  );

  useEffect(() => {
    if (isError && error) {
      toast.error(error instanceof Error ? error.message : "Failed to load recent logs");
    }
  }, [isError, error]);

  useCatchUpScheduler(queryClient, { scopedKey, appKey, executionId, since, isWaitingForUptime, logHintVersion });

  const allEntries = useMemo<LogEntry[]>(() => data ?? [], [data]);

  return { allEntries, loading: isPending };
}
