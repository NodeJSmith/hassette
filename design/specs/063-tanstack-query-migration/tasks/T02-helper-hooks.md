---
task_id: "T02"
title: "Create helper hooks and time-window utilities"
status: "done"
depends_on: ["T01"]
implements: ["FR#5", "FR#7", "FR#8", "AC#8", "AC#10", "AC#12"]
---

## Summary

Create the three building blocks that scoped page migrations depend on: `resolveSince` + `PRESET_WINDOW_SECONDS` extracted to a utility module, `useScopedQuery` wrapping `useQuery` with time-window scoping, and `useQueryInvalidator` replacing `useFilteredSignalRefetch` with signal→cache-invalidation. These hooks are new files — no existing code is modified except the extraction of `resolveSince` from the hook being deleted.

## Prompt

### 1. Create `frontend/src/utils/time-window.ts`

Extract from `frontend/src/hooks/use-scoped-api.ts` (lines 30-50):
- `PRESET_WINDOW_SECONDS` constant — maps `"1h" → 3600`, `"24h" → 86400`, `"7d" → 604800`
- `resolveSince(preset, uptimeSeconds)` function — returns the Unix timestamp boundary for the query window

The `resolveSince` logic:
- For `"since-restart"`: if `uptimeSeconds` is null, return `undefined`; otherwise return `Date.now() / 1000 - uptimeSeconds`
- For fixed-window presets: return `Date.now() / 1000 - PRESET_WINDOW_SECONDS[preset]`

Read `frontend/src/hooks/use-scoped-api.ts` lines 30-50 for the exact implementation.

### 2. Create `frontend/src/utils/time-window.test.ts`

Test scenarios from design doc "Test Strategy > time-window.test.ts":
- `resolveSince` returns `Date.now()/1000 - uptimeSeconds` for `since-restart`
- `resolveSince` returns `Date.now()/1000 - PRESET_WINDOW_SECONDS[preset]` for 1h, 24h, 7d
- `resolveSince` returns `undefined` for `since-restart` when `uptimeSeconds` is null
- `resolveSince` returns a valid number for fixed-window presets even when `uptimeSeconds` is null
- `PRESET_WINDOW_SECONDS` has correct values (3600, 86400, 604800)

Follow the test patterns in `frontend/src/utils/format.test.ts` or `frontend/src/utils/handler-ids.test.ts` for conventions.

### 3. Create `frontend/src/hooks/use-scoped-query.ts`

Wraps `useQuery` with time-window scoping. Reads `effectiveTimePreset` and `uptimeSeconds` from `useAppState()`, computes `since` using `resolveSince()` from `../utils/time-window`, and gates fetching via `enabled`.

Signature:
```typescript
export function useScopedQuery<T>(
  baseKey: readonly unknown[],
  fetcher: (since: number) => Promise<T>,
  options?: { placeholderData?: typeof keepPreviousData },
): UseQueryResult<T>
```

The optional `options` parameter forwards supported `useQuery` options. Currently only `placeholderData` is needed (by AppDetailPage in T06 for stale-while-revalidate). Spread `options` into the `useQuery` call.

Key behaviors:
- Computes `waitingForUptime = preset === "since-restart" && uptimeSeconds === null`
- Sets `enabled: !waitingForUptime`
- Query key: `[...baseKey, preset, ...(preset === "since-restart" ? [uptimeSeconds] : [])]`
  - For `since-restart`, `uptimeSeconds` is in the key because it defines the window boundary
  - For fixed-window presets, `uptimeSeconds` is NOT in the key so cache entries survive reconnects
- Calls `fetcher(since)` where `since = resolveSince(preset, uptimeSeconds)`
- Uses the factory default `staleTime: 30_000` — no override

Read `frontend/src/hooks/use-scoped-api.ts` (full file, 82 lines) for the existing implementation being replaced.

### 4. Create `frontend/src/hooks/use-scoped-query.test.ts`

Test scenarios from design doc "Test Strategy > use-scoped-query.test.ts":
- Blocks fetches until `uptimeSeconds` is available (`enabled` gate)
- Fetches once `uptimeSeconds` arrives
- Computes correct `since` for each preset (since-restart, 1h, 24h, 7d)
- Respects `effectiveTimePreset` (URL override via `urlWindowParam`)
- Refetches when preset changes (query key change)
- Refetches when `uptimeSeconds` changes for `since-restart` preset (uptime in key)
- Does NOT refetch when `uptimeSeconds` changes for fixed-window presets (uptime not in key)
- Does not refetch when `timePreset` changes while `urlWindowParam` is overriding

Use `renderHookWithProviders` from `frontend/src/test/query-test-utils.ts` (created in T01) for rendering. Use MSW to mock API responses.

### 5. Create `frontend/src/hooks/use-query-invalidator.ts`

Replaces `useFilteredSignalRefetch`. Subscribes to a Preact signal via `useSignalEffect`, applies a filter function, and calls `queryClient.invalidateQueries({ queryKey })` after a debounce (500ms trailing + 1500ms max-wait).

Re-export the debounce constants:
```typescript
export const WS_DEBOUNCE_DELAY_MS = 500;
export const WS_DEBOUNCE_MAX_WAIT_MS = 1500;
```

Signature:
```typescript
export function useQueryInvalidator<T>(
  signal: ReadonlySignal<T>,
  filterFn: (value: T) => boolean,
  queryKey: readonly unknown[],
  delayMs: number,
  maxWaitMs: number,
): void
```

Key behaviors:
- Subscribes to `signal` via `useSignalEffect`
- When `filterFn(value)` returns true: reset the trailing timer, start the max-wait timer if not already running
- Trailing timer fires after `delayMs` of no new matching events → call `queryClient.invalidateQueries({ queryKey })`
- Max-wait timer fires after `maxWaitMs` from the first matching event → call `invalidateQueries` regardless of trailing timer
- Max-wait timer does NOT reset on subsequent events (only trailing resets)
- Cleanup both timers on unmount
- Uses `useQueryClient()` to access the query client

Read `frontend/src/hooks/use-filtered-signal-refetch.ts` (full file, 105 lines) for the existing debounce algorithm being replicated.

### 6. Create `frontend/src/hooks/use-query-invalidator.test.ts`

Test scenarios from design doc "Test Strategy > use-query-invalidator.test.ts":
- Does not invalidate on mount (no spurious initial fetch)
- Invalidates after `delayMs` when filter matches
- Does not invalidate when filter returns false
- Max-wait timer fires during sustained events (trailing timer never settles)
- Max-wait timer does NOT reset on subsequent matching events (only trailing resets)
- Cleans up both timers on unmount (no dangling timeouts)

Use `vi.useFakeTimers()` for timing control. Use `renderHookWithProviders` for rendering.

## Focus

- `frontend/src/utils/` already exists with 20 files. `time-window.ts` follows existing conventions.
- The `resolveSince` function in `use-scoped-api.ts` uses `MS_PER_SECOND` from `../utils/format`. Check whether this constant is needed in `time-window.ts` or if the function uses raw division.
- The `useScopedQuery` hook reads `effectiveTimePreset` from AppState — this is a `Computed<TimePreset>` signal (see `create-app-state.ts` line ~205). The hook must read `.value` from it.
- The `useQueryInvalidator` debounce algorithm is the critical invariant: trailing edge resets, max-wait does NOT reset. The existing implementation in `use-filtered-signal-refetch.ts` lines 65-88 is the reference — replicate the timing behavior exactly.
- The `WS_DEBOUNCE_DELAY_MS` and `WS_DEBOUNCE_MAX_WAIT_MS` constants are imported by 7 source files and 1 test file from `use-filtered-signal-refetch.ts`. Those imports will be updated in later tasks (T06, T07) to point at `use-query-invalidator.ts`.
- `queryClient.invalidateQueries({ queryKey })` uses TanStack's prefix matching — passing `["app-listeners", appKey]` invalidates all keys starting with those segments.

## Verify

- [ ] FR#5: `useQueryInvalidator` applies 500ms trailing debounce with 1500ms max-wait — verified by timer-based unit tests
- [ ] FR#7: `useScopedQuery` blocks fetches when `uptimeSeconds` is null and preset is `since-restart` — verified by unit test showing `enabled: false` when uptime unavailable
- [ ] FR#8: `useScopedQuery` produces distinct query keys per preset — verified by unit test showing key changes on preset switch
- [ ] AC#8: switching presets triggers a new fetch (different query key) — verified by unit test
- [ ] AC#10: sustained burst produces at most one invalidation per max-wait window — verified by timer-based unit test
- [ ] AC#12: scoped queries show no fetch until uptime is received — verified by unit test
