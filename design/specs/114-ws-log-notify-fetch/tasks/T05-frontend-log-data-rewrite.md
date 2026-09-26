---
task_id: "T05"
title: "Rewrite use-log-data for hint-triggered REST fetch"
status: "done"
depends_on: ["T03", "T04"]
implements: ["FR#6", "FR#7", "FR#8", "AC#4", "AC#5", "AC#6", "AC#9", "AC#10"]
---

## Summary
Rewrite `use-log-data.ts` to replace the WS log merge pattern with hint-triggered REST fetches. On `log_hint` (signaled via `logHintVersion` from T04), debounce-with-maxWait, fetch from `GET /logs/since/{lastSeenId}` (from T03) preserving the view's filter set, merge into the TanStack Query cache, track per-instance `lastSeenId` cursor, implement bounded catch-up loop, and handle cursor regression. Add `getLogsSince()` to `endpoints.ts`.

## Target Files
- modify: `frontend/src/components/shared/log-table/use-log-data.ts`
- modify: `frontend/src/api/endpoints.ts`
- modify: `frontend/src/components/shared/log-table/use-log-data.test.ts`
- modify: `frontend/src/test/log-data-test-utils.ts`
- read: `frontend/src/hooks/use-scoped-query.ts` (for cache key structure, query invalidation)
- read: `frontend/src/components/shared/log-table/types.ts` (for `rowKey()`)
- read: `frontend/src/hooks/use-websocket.ts` (for `INITIAL_BACKOFF_MS`/`MAX_BACKOFF_MS` pattern)
- read: `design/specs/114-ws-log-notify-fetch/design.md`

## Prompt
In `frontend/src/api/endpoints.ts`:

1. Add a new `getLogsSince()` function for cursor-based catch-up fetches. It calls `GET /logs/since/{since_id}` with the same filter params as `getRecentLogs()` (`app_key`, `execution_id`, `level`, `since`, `source_tier`, `limit`). The existing `getRecentLogs()` is unchanged.

In `frontend/src/components/shared/log-table/use-log-data.ts`:

2. **Remove the WS merge path entirely.** The current hook merges WS-pushed entries (from `getLogEntries()` store selector) with REST-fetched entries. After T04, there's no WS content to merge — the store no longer has `getLogEntries`/`logBuffer`.

3. **Subscribe to `logHintVersion`** from the Zustand store (added in T04). When it changes, trigger a debounced REST fetch.

4. **Debounce-with-maxWait coalescing:** Use ~200ms debounce window and ~500ms `maxWait` cap. Each `logHintVersion` change resets the debounce timer, but `maxWait` guarantees a fetch fires at least every 500ms even under continuous hints. Use the existing `clearTimeout`/`setTimeout` pattern from `use-log-filters.ts`, extended with a `maxWait` tracking ref.

5. **Hint-triggered fetch:** When the debounce fires, call `getLogsSince(lastSeenId, { ...currentFilters })` — the fetch MUST carry the same filter set (`appKey`, `executionId`, `level`, `source_tier`, `since`) as the view's existing base query. Route through `queryClient.fetchQuery` against the same cache key that `useScopedQuery` uses, so TanStack retry/backoff and error-state propagation apply.

6. **Merge fetched batch:** Write the fetched records into the TanStack Query cache entry via `queryClient.setQueryData` — append to the existing data, dedup by `rowKey()`.

7. **Cursor tracking:** `lastSeenId` is derived from the max `id` in the TanStack Query cache entry — not maintained as separate local state. Each `useLogData` hook instance tracks its own `lastSeenId` from its own scoped cache entry (per-hook-instance, not global). Recompute on every write to the cache (base fetch, hint-triggered, preset change, invalidation).

8. **Bounded catch-up loop:** If a fetch returns a full page (`results.length === limit`), re-fetch with the new `lastSeenId`. Bounds: max 5 consecutive full-page fetches per episode, minimum 100ms inter-fetch delay, exponential backoff on non-2xx (reuse `INITIAL_BACKOFF_MS`/`MAX_BACKOFF_MS`/`BACKOFF_MULTIPLIER` from `use-websocket.ts`). If cap reached, stop — next hint triggers another round.

9. **Cursor regression guard:** If a fetch returns a max `id` smaller than the current `lastSeenId`, reset `lastSeenId` to the fresh value. Optionally surface a one-time "log stream reset" notice (toast or console warning).

10. **Reconnect handling:** On WS reconnect (`logHintVersion` will bump once the WS re-subscribes and a new hint arrives), the stale `lastSeenId` naturally triggers a catch-up fetch that fills the gap. No special reconnect logic needed beyond what the cursor already provides.

11. **Update `use-log-data.test.ts`** — rewrite tests for the new pattern:
    - Hint-triggered fetch fires after debounce
    - Debounce coalescing: multiple hints within 200ms → 1 fetch
    - maxWait cap: sustained hints → fetch fires every 500ms
    - Fetched records merge into cache, deduped by `rowKey()`
    - `lastSeenId` advances to max `id` in response
    - Cursor regression: max `id` < `lastSeenId` → reset
    - Catch-up loop: full page → re-fetch; 5-page cap → stop
    - View filters preserved in hint-triggered fetch

12. **Update `frontend/src/test/log-data-test-utils.ts`** — remove `WsLogPayload` import, rewrite helpers for the REST-only fetch pattern.

## Focus
- The current `use-log-data.ts` (line 54-61) calls `getRecentLogs()` via `useScopedQuery` with `appKey`, `limit`, `executionId`, `since` params. The base query stays — only the incremental update mechanism changes.
- `useScopedQuery` (in `use-scoped-query.ts`) wraps `useQuery` with time-window scoping. Its query key includes `preset` and `uptimeSeconds`. Preset changes and reconnect-driven `invalidateQueries()` will refetch the base query and reset the cache — `lastSeenId` must recompute from whatever lands in the cache, not persist across invalidations.
- `rowKey()` in `types.ts` (lines 46-61) primarily keys on `(timestamp, seq)`, falling back to `(timestamp, logger_name, lineno)` when `seq` is null. REST entries always carry `seq`, so the primary key path applies.
- The existing `REST_FETCH_LIMIT` (1000) in constants may be the right limit for catch-up fetches. Check what the base query uses.
- `use-websocket.ts` has `INITIAL_BACKOFF_MS = 1000`, `MAX_BACKOFF_MS = 30000`, `BACKOFF_MULTIPLIER = 2` for WS reconnect — reuse these constants (or reference them) for the catch-up backoff.
- This is the most complex task — it touches the core data flow for log tailing. The behavioral invariant is: logs stream in real-time with the same columns, filters, and sorting as today. The mechanism changes, the UX does not.

## Verify
- [ ] FR#6: On `log_hint`, a debounced REST fetch fires using `lastSeenId` and the view's filter set
- [ ] FR#7: 10+ hints within 100ms produce only 1 REST fetch
- [ ] FR#8: After WS reconnect, `lastSeenId` catches up missed records without manual refresh
- [ ] AC#4: Log table displays entries with execution linking metadata fetched from REST
- [ ] AC#5: Under a burst of 10+ log_hint messages within 100ms, only 1 REST fetch is issued
- [ ] AC#6: After WS reconnect, disconnected-period entries appear without manual refresh; cursor survives server restarts
- [ ] AC#9: If catch-up fetch returns max `id` below current `lastSeenId`, cursor resets and notice is surfaced
- [ ] AC#10: Catch-up loop fires at most 5 consecutive full-page fetches with at least 100ms between them, backs off on non-2xx
