# Design: Migrate Data Fetching to TanStack Query

**Date:** 2026-05-22
**Status:** approved
**Scope-mode:** hold
**Issue:** #820

## Problem

The frontend uses three custom data-fetching hooks (`useApi`, `useScopedApi`, `useFilteredSignalRefetch`) that hand-roll ~40% of what a mature data-fetching library provides — race protection, loading/error state, reconnect refetch, debounced cache invalidation. The remaining 60% (response caching, stale-while-revalidate, automatic retry with backoff, request deduplication, abort-on-unmount, garbage collection) is absent, causing:

- **Redundant API calls**: navigating away and back re-fetches data that hasn't changed
- **No retry on transient failures**: a single network blip shows an error with no recovery
- **No request cancellation**: unmounting a component doesn't abort its in-flight request, leading to wasted bandwidth and potential state writes to unmounted components
- **Manual race protection**: every hook instance manages its own `requestIdRef` counter — a pattern that the library handles internally

A fourth hook, `useManifestFetcher`, duplicates the same hand-rolled fetch pattern (race protection via `requestIdRef`, manual loading/error signal management, reconnect refetch via signal subscription) for app manifest data. It is architecturally identical to `useApi` and equally replaceable.

## Goals

- Eliminate all custom data-fetching hooks in favor of a single library-backed approach
- Enable response caching so page navigation serves cached data instead of re-fetching
- Add automatic retry with backoff for transient server errors
- Cancel in-flight requests when components unmount or query parameters change
- Preserve the existing debounced cache invalidation behavior for real-time event updates (500ms trailing, 1500ms max-wait)
- Preserve the immediate (non-debounced) cache invalidation on connection recovery

## Non-Goals

- Migrating `useTelemetryHealth` — it is a polling side-effect with custom adaptive backoff, not a data-fetching hook. Different architectural pattern, out of scope.
- Migrating consumers of `useTelemetryHealth`'s output signals (`telemetryDegraded`, `droppedOverflow`, etc.) — those signals are written by a polling side-effect, not a data-fetching hook.
- Adding prefetching for likely-next navigations — the library supports it, but scoping this to fetching parity, not new features.
- Changing the WebSocket event architecture — the signal-based dispatch (`invocationCompleted`, `executionCompleted`) remains; only the refetch trigger mechanism changes.

## User Scenarios

### Operator: Monitoring automation health

- **Goal:** Check automation status across pages without unnecessary delays
- **Context:** Navigating between apps list, app detail, and handlers pages during active monitoring

#### Page navigation with cached data

1. **Views the apps dashboard**
   - Sees: app grid with live status, stats strip, recent activity
   - Decides: clicks into an app for detail view
   - Then: app detail loads, showing listeners and jobs

2. **Navigates back to apps dashboard**
   - Sees: cached dashboard data immediately (no spinner), background refresh if stale
   - Decides: checks a different app
   - Then: navigation is instant for cached pages

#### Real-time updates during active monitoring

1. **Views app detail page while automations fire**
   - Sees: listener and job tables with current stats
   - Decides: watches as events arrive
   - Then: tables refresh within 1500ms of new events, without redundant fetches during bursts

#### Recovery from transient failure

1. **Experiences a brief network interruption**
   - Sees: no immediate error (retry in progress)
   - Decides: continues monitoring
   - Then: data loads after automatic retry; if all retries fail, sees error state

#### Connection recovery

1. **WebSocket reconnects after server restart**
   - Sees: brief reconnection indicator
   - Decides: no action needed
   - Then: all visible data refreshes immediately (not debounced) with fresh server state

## Functional Requirements

- **FR#1** All data-fetching call sites use the library's query hooks — no remaining custom data-fetching hooks (`useApi`, `useScopedApi`, `useFilteredSignalRefetch`, `useManifestFetcher`, or the hand-rolled fetch in `useLogData`)
- **FR#2** Navigating away from a page and returning within 30 seconds serves cached data without a new network request
- **FR#3** Transient server errors (HTTP 5xx, network errors) retry automatically up to 2 times with backoff; client errors (HTTP 4xx) do not retry
- **FR#4** Unmounting a component or changing query parameters cancels any in-flight request for the previous query
- **FR#5** Real-time event signals trigger cache invalidation with 500ms trailing debounce and 1500ms max-wait cap, matching the current behavior
- **FR#6** Connection recovery (reconnect after disconnect) triggers immediate invalidation of all active query caches, bypassing debounce
- **FR#7** Time-window-scoped queries gate on server uptime availability — no fetch fires until the uptime value is received from the server
- **FR#8** Time-window-scoped queries treat each preset (since-restart, 1h, 24h, 7d) as a distinct cache entry — switching presets fetches the new window's data, returning to a previous preset serves cached data if still fresh
- **FR#9** Manifest data fetches once on mount and refetches on connection recovery; all consumers read from the query cache directly — no shared state signals for manifest data
- **FR#10** The on-demand fetch pattern (command palette: fetch only when opened) is preserved — data loads on first open and serves cached results on subsequent opens within the cache window

## Edge Cases

- **Rapid preset switching**: changing the time preset multiple times quickly should cancel previous in-flight fetches and only complete the latest one
- **Burst of real-time events**: 50 events arriving in 5 seconds should produce at most ~4 fetches (capped by the 1500ms max-wait), not 50
- **Component unmount during fetch**: navigating away mid-request should not cause errors or state writes to unmounted components
- **Concurrent identical requests**: two components requesting the same data should share one network request, not fire two
- **Reconnect during active refetch**: if a connection recovery happens while a debounced refetch timer is pending, the immediate reconnect invalidation should fire regardless of the pending timer
- **`isPending` vs `isFetching` semantics**: initial load (no cached data) should show a spinner (`isPending`); background refetches with existing cached data should not show a spinner (use `isFetching` only where a refetch indicator is desired)
- **Stale data display during refetch**: app detail page currently shows previous data while fetching new data after parameter changes (stale refs) — this must be preserved via the library's keep-previous-data feature
- **Error type change**: current hooks store errors as strings; the library stores them as `Error` objects. Every error display (`{error}`) must change to `{error?.message}` or will render `[object Error]`
- **Response unwrapping**: `getManifests()` returns a wrapper object (`{ total, running, ..., manifests }`) — the manifest query must select `.manifests` from the response, not return the wrapper to consumers

## Acceptance Criteria

- **AC#1** No imports of `useApi`, `useScopedApi`, `useFilteredSignalRefetch`, or `useManifestFetcher` remain in source files; `useLogData` no longer contains a hand-rolled fetch pattern; `AppState` no longer contains `manifests`, `manifestsLoading`, `manifestsError`, or `reconnectVersion` signals (verifiable via grep for old hook imports, code review of `use-log-data.ts` and `create-app-state.ts`) — maps to FR#1
- **AC#2** Navigating apps → app-detail → apps shows cached data on return without a network request visible in browser DevTools (within the 30s cache window) — maps to FR#2
- **AC#3** Simulating a 503 response followed by a 200 response shows automatic recovery without user action — maps to FR#3
- **AC#4** All existing frontend tests pass after migration — behavioral parity
- **AC#5** All existing E2E tests pass — no visual or behavioral regressions
- **AC#6** TypeScript compilation succeeds with no errors — maps to FR#1
- **AC#7** The command palette fetches handler data on first open and serves cached data on subsequent opens — maps to FR#10
- **AC#8** Changing the time preset triggers a new fetch (different query key) rather than serving data from the previous preset's cache — maps to FR#8
- **AC#9** Navigating away from a page while a fetch is in-flight produces no errors, console warnings, or state writes to the unmounted component — maps to FR#4
- **AC#10** A sustained burst of real-time events (10+ events in 2 seconds) produces at most one fetch per 1500ms window — maps to FR#5
- **AC#11** After a WebSocket reconnection, all data visible on the current page refreshes immediately (within one render cycle, not debounced) — maps to FR#6
- **AC#12** On initial page load, scoped queries (time-window-based) show no network request until the server's uptime value is received via WebSocket — maps to FR#7

## Key Constraints

- The library's native Preact adapter must be used — no `preact/compat` shim required or permitted
- Manifest signals (`manifests`, `manifestsLoading`, `manifestsError`) are removed from `AppState` entirely — all consumers migrate to direct `useQuery` calls. No bridge or shim between the query cache and signals
- The `reconnectVersion` signal is removed entirely. All three consumers (`use-api.ts`, `use-manifest-fetcher.ts`, `use-log-data.ts`) are deleted or migrated by this work — zero consumers remain. Remove the signal from `AppState` in `create-app-state.ts` and the increment from `use-websocket.ts` (the reconnect invalidation path is now `queryClient.invalidateQueries()` directly)
- Test migration must move from module-level hook mocks (`vi.mock("../hooks/use-api")`) to MSW-backed response control — the old mock pattern cannot coexist with the library's internal state management

## Dependencies and Assumptions

- `@tanstack/preact-query` package — native Preact adapter, no additional compatibility layer needed
- MSW (Mock Service Worker) — already configured in `frontend/src/test/` for API response mocking
- Assumes the library's `keepPreviousData` (`placeholderData`) feature reproduces the stale-ref pattern used in `app-detail.tsx` for showing previous data during parameter changes
- Assumes the library's `enabled` option provides the same gating behavior as `useScopedApi`'s `waitingForUptime` check

## Architecture

### Package and provider setup

Install `@tanstack/preact-query`. Create `frontend/src/lib/query-client.ts` exporting a `createQueryClient()` factory with project defaults:
- `staleTime: 30_000` (30s) — uniform across all queries; WebSocket event invalidation handles real-time freshness
- `retry`: up to 2 attempts, only for non-4xx errors
- `gcTime: 300_000` (5 minutes)
- `refetchOnWindowFocus: false` — a monitoring dashboard should not refetch all queries on every alt-tab; the design's own debounce mechanism handles controlled refetches
- `refetchOnReconnect: false` — browser network reconnects are handled by the WebSocket reconnect invalidation path; the default would add a redundant uncontrolled refetch burst

In `frontend/src/app.tsx`, wrap the existing `AppStateContext.Provider` with `QueryClientProvider`, creating the client via `useMemo(() => createQueryClient(), [])`.

### Helper hooks

**`frontend/src/hooks/use-scoped-query.ts`** — wraps `useQuery` with time-window scoping. Reads `effectiveTimePreset` and `uptimeSeconds` from `useAppState()`, computes `since` using the existing `resolveSince` function (extracted to `frontend/src/utils/time-window.ts`), and sets `enabled: !waitingForUptime`. Query keys conditionally include `uptime`: `[...base, preset, ...(preset === "since-restart" ? [uptime] : [])]`. For `since-restart`, `uptime` defines the window boundary and must be in the key; for fixed-window presets (`1h`, `24h`, `7d`), the boundary is `Date.now() - PRESET_WINDOW_SECONDS[preset]` and `uptime` is irrelevant — including it would orphan cache entries on reconnect. Uses the default `staleTime: 30_000` from the factory — no override needed. The theoretical time-window shift over 30 seconds is negligible (especially for 1h/24h/7d windows), and WebSocket event invalidation handles real-time freshness for active data.

**`frontend/src/hooks/use-query-invalidator.ts`** — subscribes to a Preact signal via `useSignalEffect`, applies a filter function, and calls `queryClient.invalidateQueries({ queryKey })` after a debounce (500ms trailing + 1500ms max-wait, same algorithm as the current `useFilteredSignalRefetch`). Replaces the signal→refetch pattern with signal→cache-invalidation.

### Reconnect invalidation

In `frontend/src/hooks/use-websocket.ts`, after the `"connected"` case on reconnect (`hasConnectedRef.current` is true), call `queryClient.invalidateQueries()` with no filter to invalidate all active queries. The hook calls `useQueryClient()` internally to access the client (standard TanStack pattern — `WebSocketProvider` renders inside `QueryClientProvider`, so the context is available). No signature change to `useWebSocket`. This fires immediately (not debounced), preserving the invariant documented in `create-app-state.ts` that reconnect refetches bypass debounce.

This introduces a `QueryClientProvider` context dependency to `useWebSocket`. All 20 existing tests in `use-websocket.test.ts` use bare `renderHook` with no provider wrapper — they must be updated to use a `renderHookWithProviders` helper (or equivalent) that wraps with both `AppStateContext.Provider` and `QueryClientProvider`. Add this helper to `frontend/src/test/query-test-utils.ts` alongside `createTestQueryClient()`.

### Manifest fetcher migration

Delete `useManifestFetcher` and the `ManifestProvider` component from `app.tsx`. Remove `manifests`, `manifestsLoading`, and `manifestsError` signals from `AppState` in `create-app-state.ts`.

Create a `useManifests()` hook (in `frontend/src/hooks/use-manifests.ts`) that wraps `useQuery({ queryKey: ["manifests"], queryFn: getManifests, select: (data) => data.manifests })`. Uses the factory default `staleTime: 30_000` — no override needed. The `select` option unwraps the `ManifestListResponse` wrapper so consumers receive `AppManifest[]` directly — matching the current `state.manifests.value` type. Each consumer calls `useManifests()` directly — TanStack deduplicates into a single network request regardless of how many components call it.

Consumer migration for manifest data:
```tsx
// Before (signal from AppState)
const { manifests, manifestsLoading } = useAppState();
const allManifests = manifests.value;
if (manifestsLoading.value) return <Spinner />;

// After (direct query)
const { data: manifests = [], isPending: manifestsLoading } = useManifests();
if (manifestsLoading) return <Spinner />;
```

Consumers that currently destructure `manifests` from `useAppState()`: `app.tsx` (FailedAppsAlert), `command-palette.tsx`, `sidebar.tsx`, `app-detail.tsx`, `apps.tsx`, `logs.tsx`. The utility `palette-items.ts` and `app-data.ts` receive manifests as parameters and need no changes.

Reconnect invalidation is handled globally (see above) — no per-hook reconnect subscription needed.

### Log data migration

`frontend/src/components/shared/log-table/use-log-data.ts` uses the same hand-rolled pattern being eliminated (manual `cancelled` flag, manual loading signal, reconnect refetch via `reconnectVersion` signal). It merges a REST initial batch with live WebSocket log entries using a timestamp watermark.

Replace the REST fetch with `useQuery({ queryKey: ["recent-logs", appKey, executionId], queryFn: () => getRecentLogs(...) })`. The WS merge computation moves from `computed()` signals to `useMemo` — `useSubscribe(logs.version)` (already present) forces re-renders on WS updates, and the watermark + filter logic runs inside `useMemo(() => mergeEntries(queryData, logs.toArray(), ...), [queryData, logs.version.value])`. Both query data changes and WS signal changes trigger re-renders, so the memo recomputes on either path. The `reconnectVersion` dependency is eliminated — global reconnect invalidation handles refetch. This removes the last consumer of `reconnectVersion` (the other two, `use-api.ts` and `use-manifest-fetcher.ts`, are deleted by this migration).

The return type changes: `allEntries` and `restEntries` change from `ReadonlySignal<LogEntry[]>` to `LogEntry[]`, and `loading` changes from `ReadonlySignal<boolean>` to `boolean` (from `isPending`). Consumers of `useLogData` update from `.value` access to direct access.

### Page-by-page consumer migration

Each consumer file changes from:
```tsx
// Before
const { data, loading, error, refetch } = useApi(getConfig);
const config = data.value;
if (loading.value) return <Spinner />;
if (error.value) return <div>{error.value}</div>;  // error is a string

// After
const { data: config, isPending, error } = useQuery({
  queryKey: ["config"],
  queryFn: getConfig,
});
if (isPending) return <Spinner />;
if (error) return <div>{error.message}</div>;  // error is an Error object
```

**Error display migration**: the current hooks coerce errors to strings (`e instanceof Error ? e.message : "Unknown error"`). TanStack Query stores the raw `Error` object. Every error display site changes from `{error}` or `{error.value}` to `{error.message}`. TypeScript catches most of these (type mismatch between `Error` and `string` in JSX), but error displays using truthiness checks (`{error && ...}`) will compile and render `[object Error]` if the message extraction is missed.

For scoped queries:
```tsx
// Before
const listeners = useScopedApi((since) => getAppListeners(appKey, idx, since), {
  deps: [appKey, idx],
});
useFilteredSignalRefetch(invocationCompleted, filterFn, () => void listeners.refetch(), 500, 1500);

// After — deps are in the query key; TanStack refetches when the key changes
const { data: listeners, isPending } = useScopedQuery(
  ["app-listeners", appKey, idx],
  (since) => getAppListeners(appKey, idx, since),
);
useQueryInvalidator(invocationCompleted, filterFn, ["app-listeners", appKey], 500, 1500);
```

Note: `useScopedApi`'s `deps` option does not carry over. In TanStack Query, variable dependencies (`appKey`, `idx`) go in the query key — the library refetches automatically when any key segment changes. `useScopedQuery` appends `[preset, ?(uptime)]` to the provided key base internally.

Migration order (simplest to most complex):
1. `ConfigPage` — simple `useApi`, no WS events
2. `DiagnosticsPage` — simple `useApi`, no WS events
3. `CommandPalette` — `useApi` with `lazy: true` → `enabled: open`
4. `HandlersPage` — two `useScopedApi` + two `useFilteredSignalRefetch`
5. `AppsPage` — one `useScopedApi` + two `useFilteredSignalRefetch`
6. `AppDetailPage` — two `useScopedApi` + two `useFilteredSignalRefetch` + stale-ref pattern → `keepPreviousData`
7. `ListenerDetail` — one `useScopedApi` + one `useFilteredSignalRefetch`
8. `JobDetail` — one `useScopedApi` + one `useFilteredSignalRefetch`
9. `RecentActivitySection` — one `useScopedApi` + two `useFilteredSignalRefetch`

### Stale-data display (AppDetailPage)

The current stale-ref pattern (`useRef` holding previous data while new data loads) maps to the library's `placeholderData: keepPreviousData` option. This shows previous query data while a new fetch is in-flight, exactly matching the current UX.

### Loading state semantics

The library distinguishes `isPending` (no cached data at all) from `isFetching` (any fetch in progress, including background refetches). Current pages show spinners only on initial load — they use `loading.value && data === null` guards. This maps directly to `isPending`. Pages that need to show a refetch indicator can check `isFetching` separately.

### Query key strategy

| Consumer | Query key |
|---|---|
| ConfigPage | `["config"]` |
| DiagnosticsPage | `["system-status"]` |
| CommandPalette | `["all-listeners-palette"]` |
| useManifests (shared) | `["manifests"]` |
| useLogData | `["recent-logs", appKey, executionId]` |
| HandlersPage (listeners) | `["all-listeners", preset, ?(uptime)]` |
| HandlersPage (jobs) | `["all-jobs", preset, ?(uptime)]` |
| AppsPage | `["dashboard-grid", preset, ?(uptime)]` |
| AppDetailPage (listeners) | `["app-listeners", appKey, idx, preset, ?(uptime)]` |
| AppDetailPage (jobs) | `["app-jobs", appKey, idx, preset, ?(uptime)]` |
| ListenerDetail | `["handler-invocations", listenerId, preset, ?(uptime)]` |
| JobDetail | `["job-executions", jobId, preset, ?(uptime)]` |
| RecentActivitySection | `["app-activity", appKey, idx, preset, ?(uptime)]` |

`?(uptime)` = included only when `preset === "since-restart"`; omitted for fixed-window presets.

Scoped queries include `preset` in the key unconditionally and `uptime` only when `preset === "since-restart"` (where it defines the window boundary). Fixed-window presets omit `uptime` so cache entries survive reconnects. All queries share the same `staleTime: 30_000` — scoped and non-scoped alike. WebSocket event invalidation handles real-time freshness for active data; the 30-second staleness window covers navigation-and-back without re-fetching. Invalidation uses TanStack's prefix matching: `queryClient.invalidateQueries({ queryKey: ["app-listeners", appKey] })` matches any key that starts with those segments, so it invalidates all instance/preset/uptime variants for that app in one call. This is why the invalidation key in `useQueryInvalidator` is shorter than the full query key — it intentionally targets all cache entries for the entity, not a specific preset.

### Test infrastructure changes

Update `frontend/src/test/render-helpers.tsx` to wrap the tree in `QueryClientProvider` with a test-specific `QueryClient` (`retry: false`, `staleTime: 0`). Create `frontend/src/test/query-test-utils.ts` with a `createTestQueryClient()` factory that creates a fresh client per test for isolation.

This provider change affects all 15 test files that use `renderWithAppState` — not just the ones explicitly listed above. The test query client configuration (`retry: false`, `staleTime: 0`) makes the wrapping transparent for tests that don't touch queries, but any component that now calls `useQuery` or `useManifests` inside these tests will attempt real query lifecycle behavior against MSW handlers.

All page tests migrate from:
```tsx
vi.mock("../hooks/use-api", () => ({ useApi: vi.fn() }));
useApi.mockReturnValue(fakeApiResult(data));
```
to:
```tsx
// MSW handler controls the response (already configured in test/handlers.ts)
// renderWithAppState includes QueryClientProvider automatically
const { findByText } = renderWithAppState(<ConfigPage />);
await findByText("config"); // async — waits for query to resolve
```

### Files created

- `frontend/src/lib/query-client.ts` — `createQueryClient()` factory
- `frontend/src/lib/query-client.test.ts` — factory defaults and retry logic tests
- `frontend/src/hooks/use-scoped-query.ts` — time-window-scoped query wrapper
- `frontend/src/hooks/use-scoped-query.test.ts` — scoped query gating, key strategy, preset switching tests
- `frontend/src/hooks/use-query-invalidator.ts` — debounced cache invalidation from signals; re-exports `WS_DEBOUNCE_DELAY_MS` and `WS_DEBOUNCE_MAX_WAIT_MS` constants (migrated from the deleted `use-filtered-signal-refetch.ts`)
- `frontend/src/hooks/use-query-invalidator.test.ts` — debounce timing, filter logic, max-wait, cleanup tests
- `frontend/src/hooks/use-manifests.ts` — `useManifests()` wrapper around `useQuery` for shared manifest data
- `frontend/src/hooks/use-manifests.test.ts` — unwrapping, deduplication tests
- `frontend/src/utils/time-window.ts` — `resolveSince()` and `PRESET_WINDOW_SECONDS` extracted from `use-scoped-api.ts`
- `frontend/src/utils/time-window.test.ts` — `resolveSince` computation and constant value tests
- `frontend/src/test/query-test-utils.ts` — test `QueryClient` factory and `renderHookWithProviders` helper

### Files deleted

- `frontend/src/hooks/use-api.ts`
- `frontend/src/hooks/use-api.test.ts`
- `frontend/src/hooks/use-scoped-api.ts`
- `frontend/src/hooks/use-scoped-api.test.ts`
- `frontend/src/hooks/use-filtered-signal-refetch.ts`
- `frontend/src/hooks/use-filtered-signal-refetch.test.ts`
- `frontend/src/hooks/use-manifest-fetcher.ts`

### Files modified

- `frontend/package.json` — add `@tanstack/preact-query`
- `frontend/src/app.tsx` — add `QueryClientProvider`, replace `ManifestProvider` internals
- `frontend/src/hooks/use-websocket.ts` — add `useQueryClient()` call and reconnect invalidation
- `frontend/src/hooks/use-websocket.test.ts` — wrap all 20 test cases with `QueryClientProvider` via new helper
- `frontend/src/test/render-helpers.tsx` — add `QueryClientProvider` wrapping
- `frontend/src/pages/config.tsx` — replace `useApi` → `useQuery`
- `frontend/src/pages/config.test.tsx` — replace hook mock → MSW
- `frontend/src/pages/diagnostics.tsx` — replace `useApi` → `useQuery`
- `frontend/src/pages/diagnostics.test.tsx` — replace hook mock → MSW
- `frontend/src/components/layout/command-palette.tsx` — replace `useApi` lazy → `useQuery` enabled
- `frontend/src/pages/handlers.tsx` — replace `useScopedApi` + `useFilteredSignalRefetch` → `useScopedQuery` + `useQueryInvalidator`
- `frontend/src/pages/handlers.test.tsx` — replace hook mock → MSW
- `frontend/src/pages/apps.tsx` — replace `useScopedApi` + `useFilteredSignalRefetch` → `useScopedQuery` + `useQueryInvalidator`
- `frontend/src/pages/apps.test.tsx` — replace hook mock → MSW
- `frontend/src/pages/app-detail.tsx` — replace `useScopedApi` + `useFilteredSignalRefetch` → `useScopedQuery` + `useQueryInvalidator` + `keepPreviousData`; replace `state.manifests` → `useManifests()`
- `frontend/src/pages/app-detail.test.tsx` — replace hook mock → MSW
- `frontend/src/pages/logs.tsx` — replace `state.manifests` → `useManifests()`
- `frontend/src/components/shared/log-table/use-log-data.ts` — replace hand-rolled REST fetch + `reconnectVersion` dep with `useQuery`; replace `computed()` signal merge with `useMemo` over query data + WS signals
- `frontend/src/components/shared/log-table/use-log-data.test.ts` — update tests for query-based fetch (remove `reconnectVersion` trigger tests, add MSW-backed fetch tests)
- `frontend/src/components/shared/log-table/use-log-table.tsx` — update `useLogData` return type usage (signals → plain values)
- `frontend/src/components/shared/log-table/use-log-filters.ts` — update `allEntries`/`restEntries` parameter types from `ReadonlySignal<LogEntry[]>` to `LogEntry[]`; remove `.value` reads
- `frontend/src/components/app-detail/listener-detail.tsx` — replace `useScopedApi` + `useFilteredSignalRefetch`
- `frontend/src/components/app-detail/job-detail.tsx` — replace `useScopedApi` + `useFilteredSignalRefetch`
- `frontend/src/components/app-detail/recent-activity-section.tsx` — replace `useScopedApi` + `useFilteredSignalRefetch`
- `frontend/src/components/layout/sidebar.tsx` — replace `state.manifests` → `useManifests()`
- `frontend/src/components/app-detail/overview-tab.test.tsx` — update `WS_DEBOUNCE_MAX_WAIT_MS` import from deleted hook to `use-query-invalidator`
- `frontend/src/components/layout/command-palette.test.tsx` — replace `manifests`/`manifestsLoading` state overrides with MSW-backed manifest responses; update for `lazy: true` → `enabled: isOpen` migration (switch to async assertions)
- `frontend/src/components/layout/sidebar.test.tsx` — replace `manifests`/`manifestsLoading` state overrides with MSW-backed manifest responses
- `frontend/src/pages/logs.test.tsx` — replace `manifests`/`manifestsLoading` state overrides with MSW-backed manifest responses
- `frontend/src/components/shared/log-table/use-log-table.test.tsx` — update `useLogData` mock return values from `signal([])` to plain arrays; update `loading` mock from signal to boolean
- `frontend/src/components/shared/log-table/use-log-filters.test.ts` — change `allEntries`/`restEntries` parameters from `signal<LogEntry[]>(...)` to plain `LogEntry[]` arrays; replace `.value = [...]` mutations with re-renders
- `frontend/src/state/create-app-state.ts` — remove `manifests`, `manifestsLoading`, `manifestsError`, and `reconnectVersion` signals; update comments referencing `useManifestFetcher` and `useFilteredSignalRefetch`

## Convention Examples

### Simple `useApi` consumer (ConfigPage)

**Source:** `frontend/src/pages/config.tsx`

```tsx
const result = useApi(getConfig);
const config = result.data.value;
const loading = result.loading.value;
const error = result.error.value;
// ...
{loading && <Spinner />}
{error && <div class="ht-alert ht-alert--danger">{error}</div>}
{config && <div>{/* render */}</div>}
```

This pattern (signal `.value` reads, ternary loading/error/data guards) repeats in every consumer and is the primary migration target.

### Scoped query + WS invalidation (HandlersPage)

**Source:** `frontend/src/pages/handlers.tsx`

```tsx
const listenersApi = useScopedApi((since) => getAllListeners(since));
const jobsApi = useScopedApi((since) => getAllJobs(since));

useFilteredSignalRefetch(
  invocationCompleted,
  () => true,
  () => void listenersApi.refetch(),
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
);
```

This is the canonical scoped + invalidation pattern. Each `useScopedApi` call pairs with a `useFilteredSignalRefetch` call. The migration replaces both in lockstep.

### Hook-mock test pattern (being replaced)

**Source:** `frontend/src/pages/config.test.tsx`

```tsx
vi.mock("../hooks/use-api", () => ({ useApi: vi.fn() }));
const useApiMod = await import("../hooks/use-api");
const useApi = useApiMod.useApi as unknown as ReturnType<typeof vi.fn>;

function fakeApiResult<T>(data: T | null, loading = false, error: string | null = null) {
  return {
    data: signal(data),
    loading: signal(loading),
    error: signal(error),
    refetch: vi.fn(),
  };
}

useApi.mockReturnValue(fakeApiResult(createSystemConfig()));
```

Every page test follows this pattern. After migration, tests use MSW handlers + `await findByText` instead of synchronous signal mocks.

### Stale-ref pattern (AppDetailPage)

**Source:** `frontend/src/pages/app-detail.tsx`

```tsx
const staleListeners = useRef<typeof listeners.data.value>(null);
if (listeners.data.value) staleListeners.current = listeners.data.value;
const displayListeners = listeners.data.value ?? staleListeners.current ?? [];
```

This hand-rolled stale-while-revalidate is replaced by the library's `placeholderData: keepPreviousData` option.

### WebSocket reconnect invalidation point

**Source:** `frontend/src/hooks/use-websocket.ts`

```tsx
if (hasConnectedRef.current) {
  state.logs.clear();
  state.serviceStatus.value = {};
  state.reconnectVersion.value = state.reconnectVersion.value + 1;
}
```

The reconnect handler in `use-websocket.ts` is where `queryClient.invalidateQueries()` will be added. The `reconnectVersion` increment is removed from this block — all three consumers are eliminated by this migration (see Key Constraints).

## Alternatives Considered

### Keep custom hooks, add caching layer

Add response caching as a separate module that `useApi` reads from/writes to. Rejected because it requires reimplementing cache invalidation, garbage collection, and stale-while-revalidate — exactly the work the library already does. Increasing the custom surface area when a well-maintained library covers the use case is not justified.

### SWR instead of TanStack Query

SWR is lighter-weight and simpler. Rejected because: (a) no native Preact adapter — requires `preact/compat`, (b) no built-in support for query cancellation via AbortController, (c) less granular cache invalidation (no query key prefix matching). TanStack Query's Preact adapter is first-party and avoids the compat shim.

### Bridge manifest query results to AppState signals

Replace the fetch mechanism but keep `state.manifests`, `state.manifestsLoading`, `state.manifestsError` signals, syncing TanStack state back via a `useEffect`. Rejected because it creates a backwards-compatibility shim that exists only to avoid editing ~3 additional files. The bridge adds a second state management layer for the same data, which is confusing to read and maintain. The extra consumer files are a small addition to an already-large migration.

### Drop debounce, rely on TanStack deduplication

Remove the 500ms/1500ms debounce and let TanStack Query's built-in deduplication handle burst events. Rejected because deduplication only collapses concurrent requests for the same key — it doesn't prevent rapid sequential invalidations. During sustained WS bursts (50 events in 5 seconds), each `invalidateQueries` call would trigger a new fetch as soon as the previous one resolves, producing ~25 fetches instead of ~4.

## Test Strategy

### New unit tests

**`frontend/src/hooks/use-query-invalidator.test.ts`** (new file):
- Does not invalidate on mount (no spurious initial fetch)
- Invalidates after `delayMs` when filter matches
- Does not invalidate when filter returns false
- Max-wait timer fires during sustained events (trailing timer never settles)
- Max-wait timer does NOT reset on subsequent matching events (only the trailing timer resets)
- Cleans up both timers on unmount (no dangling timeouts)

**`frontend/src/hooks/use-scoped-query.test.ts`** (new file — migrates and extends `use-scoped-api.test.ts`):
- Blocks fetches until `uptimeSeconds` is available (`enabled` gate)
- Fetches once `uptimeSeconds` arrives
- Computes correct `since` for each preset (since-restart, 1h, 24h, 7d)
- Respects `effectiveTimePreset` (URL override via `urlWindowParam`)
- Refetches when preset changes (query key change)
- Refetches when `uptimeSeconds` changes for `since-restart` preset (uptime in key)
- Does NOT refetch when `uptimeSeconds` changes for fixed-window presets (uptime not in key)
- Does not refetch when `timePreset` changes while `urlWindowParam` is overriding

**`frontend/src/utils/time-window.test.ts`** (new file — migrates from `use-scoped-api.test.ts`):
- `resolveSince` returns `Date.now()/1000 - uptimeSeconds` for `since-restart`
- `resolveSince` returns `Date.now()/1000 - PRESET_WINDOW_SECONDS[preset]` for 1h, 24h, 7d
- `resolveSince` returns `undefined` for `since-restart` when `uptimeSeconds` is null
- `resolveSince` returns a valid number for fixed-window presets even when `uptimeSeconds` is null
- `PRESET_WINDOW_SECONDS` has correct values (3600, 86400, 604800)

**`frontend/src/lib/query-client.test.ts`** (new file):
- Factory returns a `QueryClient` with `staleTime: 30_000`
- Retry function returns false for 4xx errors (no retry)
- Retry function returns true for 5xx errors (up to 2 attempts)
- Retry function returns true for network errors (non-HTTP failures)
- `refetchOnWindowFocus` is false
- `refetchOnReconnect` is false

### New integration tests

**`frontend/src/hooks/use-websocket.test.ts`** (existing file — add new tests):
- On reconnect (`hasConnectedRef.current` is true), `queryClient.invalidateQueries()` is called with no filter
- On first connect, `invalidateQueries()` is NOT called
- All existing tests updated to use `renderHookWithProviders` wrapper (QueryClientProvider + AppStateContext)

**`frontend/src/hooks/use-manifests.test.ts`** (new file — MSW-backed):
- Returns `AppManifest[]` (unwrapped from `ManifestListResponse.manifests`) — MSW handler returns full `ManifestListResponse`, test verifies only `.manifests` array is exposed
- Returns empty array when query is pending (`data` default)
- Multiple components calling `useManifests()` share one network request (deduplication)

**`frontend/src/components/shared/log-table/use-log-data.test.ts`** (existing file — rewrite):
- REST fetch fires on mount via `useQuery` (MSW handler controls response)
- WS entries newer than the REST watermark are included in `allEntries`
- WS entries at or before the watermark are excluded (dedup)
- WS entries filtered by `appKey` when provided
- WS entries filtered by `executionId` when provided
- `restEntries` contains only REST data (no WS merge)
- Global reconnect invalidation triggers a refetch (remove `reconnectVersion`-specific tests)
- Error from REST fetch is surfaced (toast or error state)

### Migrated component tests (existing files — update pattern)

All page/component test files migrate from hook mocks to MSW-backed async tests:
- `config.test.tsx`, `diagnostics.test.tsx`, `handlers.test.tsx`, `apps.test.tsx`, `app-detail.test.tsx`, `command-palette.test.tsx`
- Remove `vi.mock("../hooks/use-api")` and `fakeApiResult` helpers
- Use MSW handlers from `test/handlers.ts` to control API responses
- Replace synchronous assertions (`expect(x).toBeDefined()`) with async queries (`await findByText(...)`, `waitFor(...)`)
- Key scenarios per page: loading state (`isPending` → spinner), error display (`error.message`), populated data, empty state
- `command-palette.test.tsx` specifically: simulate palette open to trigger the `enabled: isOpen` gate; replace `manifests`/`manifestsLoading` state overrides with MSW-backed manifest responses

### Failure mode coverage (distributed across test files above)

- 4xx response → verify no retry (query-client.test.ts)
- 5xx then 200 → verify retry succeeds (query-client.test.ts)
- `uptimeSeconds` null → scoped queries hold in pending state (use-scoped-query.test.ts)
- WS reconnect → all active queries refetch (use-websocket.test.ts)
- Unmount during fetch → no errors or state writes (component test — navigate away mid-load)

### E2E (Playwright)

Run full E2E suite after migration to catch visual regressions. Key flows:
- Page navigation caching (apps → detail → apps shows cached data)
- Time preset switching (triggers new fetch, returning to previous preset serves cache)
- App detail stale-data display (`keepPreviousData` shows previous instance data during load)

## Documentation Updates

- Update `create-app-state.ts` comments that reference `useManifestFetcher` and `useFilteredSignalRefetch` to describe the new architecture
- No docs-site updates needed — the data-fetching hooks are internal implementation, not documented in the user-facing docs

## Impact

**Files created:** 11 (5 source files + 1 test utility + 5 test files)
**Files deleted:** 7 (4 hook files + 3 hook test files)
**Files modified:** ~32 (16 page/component/hook files, 13 test files, 3 infrastructure files)
**Blast radius:** All pages that fetch data, plus all 15 test files using `renderWithAppState` (indirectly affected by provider wrapping). No backend changes. No CSS changes. No API contract changes.
**Dependencies added:** `@tanstack/preact-query` (well-maintained, first-party Preact support, MIT license)

The migration is self-contained within the frontend. Backend API endpoints, WebSocket message format, and response models are unchanged.

## Open Questions

None — all design decisions resolved during discovery.
