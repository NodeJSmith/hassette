---
task_id: "T05"
title: "Migrate manifest data and command palette to useQuery"
status: "done"
depends_on: ["T01"]
implements: ["FR#1", "FR#9", "FR#10", "AC#7"]
---

## Summary

Replace the `useManifestFetcher` hook and its shared AppState signals (`manifests`, `manifestsLoading`, `manifestsError`) with a `useManifests()` hook backed by TanStack Query. Migrate all six manifest consumers to call `useManifests()` directly. Also migrate the command palette's `useApi(lazy: true)` call to `useQuery(enabled)` since we're already touching that file for manifests.

## Prompt

### 1. Create `frontend/src/hooks/use-manifests.ts`

```typescript
export function useManifests() {
  return useQuery({
    queryKey: ["manifests"],
    queryFn: getManifests,
    select: (data) => data.manifests,
  });
}
```

The `select` option unwraps the `ManifestListResponse` wrapper so consumers receive `AppManifest[]` directly — matching the current `state.manifests.value` type. The `getManifests` function is in `frontend/src/api/endpoints.ts`.

Uses the factory default `staleTime: 30_000`. Reconnect invalidation is handled globally by T03's `queryClient.invalidateQueries()`.

### 2. Create `frontend/src/hooks/use-manifests.test.ts`

MSW-backed tests. Test scenarios from design doc:
- Returns `AppManifest[]` (unwrapped from `ManifestListResponse.manifests`) — MSW handler returns full `ManifestListResponse`, test verifies only `.manifests` array is exposed
- Returns empty array when query is pending (`data` default)
- Multiple components calling `useManifests()` share one network request (deduplication)

Use `renderHookWithProviders` from `frontend/src/test/query-test-utils.ts`.

### 3. Remove ManifestProvider from `frontend/src/app.tsx`

Read `app.tsx`. Remove:
- The `ManifestProvider` component definition (lines ~182-186)
- The `<ManifestProvider state={state} />` usage (line ~76)
- The `useManifestFetcher` import

### 4. Delete `frontend/src/hooks/use-manifest-fetcher.ts`

Remove the file entirely.

### 5. Migrate manifest consumers

Six files currently destructure `manifests` (and sometimes `manifestsLoading`) from `useAppState()`. Each one changes to call `useManifests()`:

**Before (each file):**
```tsx
const { manifests, manifestsLoading } = useAppState();
const allManifests = manifests.value;
if (manifestsLoading.value) return <Spinner />;
```

**After:**
```tsx
const { data: manifests = [], isPending: manifestsLoading } = useManifests();
if (manifestsLoading) return <Spinner />;
```

Files to migrate (read each one first):
1. `frontend/src/app.tsx` — `FailedAppsAlert` component uses `manifests`
2. `frontend/src/components/layout/command-palette.tsx` — uses `manifests` AND `useApi(getAllListeners, [], { lazy: true })`
3. `frontend/src/components/layout/sidebar.tsx` — uses `manifests`, `manifestsLoading`
4. `frontend/src/pages/app-detail.tsx` — uses `manifests`, `manifestsLoading`
5. `frontend/src/pages/apps.tsx` — uses `manifests`, `manifestsLoading`
6. `frontend/src/pages/logs.tsx` — uses `manifests`

For each file: remove `manifests`/`manifestsLoading`/`manifestsError` from the `useAppState()` destructure (keep other signals they use). Add `import { useManifests } from "../hooks/use-manifests"` (adjust path depth per file).

### 6. Command palette: migrate `useApi` lazy call

In `frontend/src/components/layout/command-palette.tsx`, also migrate the `useApi(getAllListeners, [], { lazy: true })` call (line 39):

**Before:**
```tsx
const listenersApi = useApi(getAllListeners, [], { lazy: true });
// on open:
void listenersApi.refetch();
```

**After:**
```tsx
const { data: listeners, isPending } = useQuery({
  queryKey: ["all-listeners-palette"],
  queryFn: () => getAllListeners(),
  enabled: open, // only fetch when palette is open
});
```

The `lazy: true` + manual `refetch()` pattern maps to `enabled: open` (the prop name is `open`, not `isOpen`). Remove the `useApi` import. Remove the manual `refetch()` call.

Note: `getAllListeners` accepts `(since?: number | null)`. Do NOT pass it directly as `queryFn: getAllListeners` — TanStack passes a `QueryFunctionContext` object as the first argument, which would be interpreted as the `since` parameter and break the API call. Always wrap: `queryFn: () => getAllListeners()`.

Update error handling in this file too — any error display changes from string to `Error` object.

### 7. Remove manifest signals from `frontend/src/state/create-app-state.ts`

Read the file. Remove these signals from `createAppState()`:
- `manifests: signal<AppManifest[]>([])` (line 116)
- `manifestsLoading: signal(true)` (line 117)
- `manifestsError: signal<string | null>(null)` (line 118)

Update any comments that reference `useManifestFetcher`. Keep `reconnectVersion` — it's removed in T09.

### 8. Update affected test files

Three test files pass `manifests`/`manifestsLoading` as `stateOverrides` to `renderWithAppState`. After removing these signals from AppState, these overrides break. Each test must provide manifest data via MSW handlers instead.

- `frontend/src/components/layout/command-palette.test.tsx` — remove manifest state overrides; add MSW handler for `/api/apps/manifests`; also update for `useApi(lazy)` → `useQuery(enabled)` migration (simulate palette open, use async assertions)
- `frontend/src/components/layout/sidebar.test.tsx` — remove `withManifests()` helper and manifest state overrides; provide manifest data via MSW handler
- `frontend/src/pages/logs.test.tsx` — same pattern as sidebar

For each test file: read the full file first, then remove manifest-related state overrides and add MSW handlers.

## Focus

- The `select: (data) => data.manifests` in `useManifests` is critical — without it, consumers would receive the full `ManifestListResponse` wrapper instead of `AppManifest[]`.
- Six source files and three test files are modified. This is a large task but all changes follow the same pattern.
- `command-palette.tsx` has TWO migrations: manifest AND useApi-lazy. Both are done here to avoid touching the file twice.
- `app-detail.tsx` and `apps.tsx` also use `useScopedApi` — do NOT migrate those calls here. Only migrate the manifest access. The scoped query migration happens in T06.
- The palette's `enabled` gate uses the `open` prop (line 25: `open: boolean` in `CommandPaletteProps`, line 29: destructured as `{ open, onClose }`).
- `getManifests` in `frontend/src/api/endpoints.ts` (line 36) returns `Promise<ManifestListResponse>`.
- After this task, `useApi` has zero remaining consumers (config and diagnostics migrated in T04, command-palette migrated here). The file is not deleted until T09.
- Utility files `palette-items.ts` and `app-data.ts` receive manifests as parameters — they need no changes.

## Verify

- [ ] FR#1: `useManifestFetcher` is deleted; `command-palette.tsx` no longer imports `useApi` — verified by file deletion and grep
- [ ] FR#9: `useManifests()` wraps `useQuery` with `select: (data) => data.manifests`; `ManifestProvider` removed from `app.tsx`; no manifest signals in `AppState` — verified by code review
- [ ] FR#10: command palette fetches on open via `enabled: open` and serves cached data on subsequent opens — verified by `command-palette.test.tsx`
- [ ] AC#7: command palette test shows cached data on subsequent opens within cache window — verified by test assertion
