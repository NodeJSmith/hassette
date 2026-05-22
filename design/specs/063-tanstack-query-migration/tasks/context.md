# Context: Migrate Data Fetching to TanStack Query

## Problem & Motivation

The frontend uses four custom data-fetching hooks (`useApi`, `useScopedApi`, `useFilteredSignalRefetch`, `useManifestFetcher`) that hand-roll race protection, loading/error state, reconnect refetch, and debounced cache invalidation. They lack response caching, stale-while-revalidate, automatic retry with backoff, request deduplication, abort-on-unmount, and garbage collection. This causes redundant API calls on navigation, no recovery from transient failures, wasted bandwidth from uncancelled requests, and repeated boilerplate across every consumer.

## Visual Artifacts

None.

## Key Decisions

1. **TanStack Query over SWR** — TanStack has a native Preact adapter (no `preact/compat` shim), built-in AbortController cancellation, and granular cache invalidation via query key prefix matching. SWR lacks all three.
2. **Uniform `staleTime: 30_000`** — all queries use the same 30-second staleness window. WebSocket event invalidation handles real-time freshness; the 30s window covers navigation-and-back without re-fetching.
3. **`refetchOnWindowFocus: false` and `refetchOnReconnect: false`** — a monitoring dashboard should not refetch on every alt-tab; browser reconnects are handled by the WebSocket reconnect invalidation path.
4. **Debounced invalidation preserved** — 500ms trailing + 1500ms max-wait cap via a new `useQueryInvalidator` hook. TanStack's built-in deduplication alone would produce ~25 fetches during a 50-event burst instead of ~4.
5. **Immediate reconnect invalidation** — `queryClient.invalidateQueries()` with no filter on WebSocket reconnect, bypassing debounce. Preserves the invariant that reconnect refetches are immediate.
6. **Manifest signals removed from AppState** — all consumers call `useManifests()` directly. No bridge/shim between query cache and signals.
7. **`reconnectVersion` signal removed entirely** — all three consumers (`use-api.ts`, `use-manifest-fetcher.ts`, `use-log-data.ts`) are deleted or migrated. Zero remaining consumers.
8. **Test migration to MSW** — module-level hook mocks (`vi.mock("../hooks/use-api")`) replaced with MSW-backed response control. Assertions change from synchronous signal reads to async queries (`await findByText`).
9. **`useMemo` for log data WS merge** — replaces Preact `computed()` signals. Dependencies: `[queryData, logs.version.value]`.
10. **`WS_DEBOUNCE_*` constants move to `use-query-invalidator.ts`** — re-exported from the new hook after `use-filtered-signal-refetch.ts` is deleted.

## Constraints & Anti-Patterns

- **No `preact/compat` shim** — the native `@tanstack/preact-query` adapter must be used.
- **No signal bridges** — do not sync TanStack state back to Preact signals via `useEffect`. Each consumer calls the query hook directly.
- **Do not migrate `useTelemetryHealth`** — it is a polling side-effect with custom adaptive backoff, not a data-fetching hook. Out of scope.
- **Do not add prefetching** — scoping to fetching parity, not new features.
- **Do not change WebSocket event architecture** — signal-based dispatch (`invocationCompleted`, `executionCompleted`) remains; only the refetch trigger mechanism changes.
- **Error type change** — current hooks store errors as strings; TanStack stores `Error` objects. Every error display must use `{error.message}`, not `{error}`. TypeScript catches most mismatches, but truthiness checks (`{error && ...}`) will compile and render `[object Error]` if the message extraction is missed.
- **`isPending` vs `isFetching`** — use `isPending` for spinners (no cached data). Do not use `isFetching` for spinners (it includes background refetches and would flash on stale-while-revalidate).
- **During migration, both reconnect mechanisms coexist** — `queryClient.invalidateQueries()` for migrated pages, `reconnectVersion` for not-yet-migrated pages. Only remove `reconnectVersion` after ALL consumers are deleted/migrated.

## Design Doc References

- `## Architecture` — full implementation plan: provider setup, helper hooks, reconnect invalidation, manifest migration, log data migration, page-by-page consumer migration
- `## Edge Cases` — rapid preset switching, burst events, unmount during fetch, concurrent requests, reconnect during refetch, isPending vs isFetching, stale data display, error type change, response unwrapping
- `## Query key strategy` — table mapping each consumer to its query key, with `?(uptime)` conditional inclusion explained
- `## Test Strategy` — concrete test scenarios for every new file, migrated test file, and failure mode
- `## Convention Examples` — real code snippets showing current patterns and their TanStack replacements

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
