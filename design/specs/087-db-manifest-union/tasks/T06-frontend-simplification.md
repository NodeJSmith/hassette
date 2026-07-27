---
task_id: "T06"
title: "Simplify frontend apps page to use grid endpoint"
status: "done"
depends_on: ["T03", "T04"]
implements: ["FR#9", "AC#8"]
---

## Summary

Remove the client-side `mergeManifestsAndGrid()` function and refactor the apps page to consume only the dashboard grid endpoint. The grid response now includes manifest metadata fields (from T04), so the apps page no longer needs a separate manifests fetch. Add a 503 error state for when the DB is unavailable. Update related frontend tests.

## Target Files

- modify: `frontend/src/pages/apps.tsx`
- modify: `frontend/src/utils/app-data.ts`
- modify: `frontend/src/hooks/use-manifests.ts`
- modify: `frontend/src/pages/apps.test.tsx`
- modify: `frontend/src/hooks/use-manifests.test.ts`
- read: `frontend/src/api/endpoints.ts` (grid endpoint function)
- read: `frontend/src/api/generated-types.ts` (regenerated types from T04)
- read: `frontend/src/state/create-app-state.ts` (appStatus signal)

## Prompt

### Delete `mergeManifestsAndGrid` in `app-data.ts`

Remove the `mergeManifestsAndGrid()` function from `frontend/src/utils/app-data.ts`. Keep the other exports (`AppRow`, `AppSortKey`, `AppSortState`, `appLiveStatus`, `compareAppRows`).

Rebuild the `AppRow` interface to match the extended `DashboardAppGridEntry` response shape (from T04's type regeneration). The grid response now includes `class_name`, `filename`, `enabled`, `auto_loaded`, `autostart`, `block_reason`, `instances`, `error_message`, `error_traceback`, `in_current_config` — so `AppRow` can be simplified to extend or mirror the grid entry type rather than merging two separate sources.

### Refactor `apps.tsx`

Currently:
```tsx
const { data: manifests = [] } = useManifests();
const { data: gridData } = useScopedQuery(...getDashboardAppGrid);
const allApps = mergeManifestsAndGrid(manifests, gridEntries);
```

After:
```tsx
const { data: gridData, error } = useScopedQuery(...getDashboardAppGrid);
const allApps = gridData?.apps ?? [];  // direct consumption, no merge
```

- Remove the `useManifests()` import and call from apps.tsx (it's no longer needed here).
- Add a 503 error state: when `error` is a 503, show a "telemetry unavailable" banner using the existing error-state pattern from other pages that handle 503.
- The `appLiveStatus` overlay from WebSocket `app_status_changed` events continues to work on top of the grid data — it reads `app_key` and `instances`, both now present in the grid response.

### Update `use-manifests.ts`

The hook is still needed by other consumers (sidebar, command palette, logs, app detail). Do NOT delete it. But verify it doesn't need changes — the `/apps/manifests` endpoint response shape may have changed (added `in_current_config`), so the hook's type annotation may need updating.

### Update frontend tests

- `apps.test.tsx`: Remove references to `mergeManifestsAndGrid`. Update test setup to provide grid data directly instead of merging manifests + grid.
- `use-manifests.test.ts`: Verify tests still pass with the updated response shape (new `in_current_config` field).

## Focus

- Check `frontend/src/api/endpoints.ts` for the function that fetches the grid endpoint (likely `getDashboardAppGrid`) — the apps page calls this via TanStack Query.
- The existing error pattern: look at other pages that handle 503 responses — likely a conditional render based on `error?.response?.status === 503` or similar. Follow the same pattern.
- `frontend/src/utils/app-data.ts` has other exports (`appLiveStatus`, `compareAppRows`, `AppSortKey`, `AppSortState`) that must be preserved — they're used by apps.tsx for sorting and live status overlay.
- The `appLiveStatus` function takes `row: Pick<AppRow, "app_key" | "status"> & { instances?: ... }` — it needs `instances` from the grid response, which T04 added. Verify the field name and shape match.
- Don't touch `sidebar.tsx`, `command-palette.tsx`, `logs.tsx`, or `app.tsx` in this task — those consume the manifests endpoint and may need `in_current_config` handling, but that's a separate concern not scoped to FR#9.

## Verify

- [ ] FR#9: The apps page consumes the grid endpoint directly with no client-side merge — verified by confirming `mergeManifestsAndGrid` is deleted from `app-data.ts` and `apps.tsx` no longer imports `useManifests`.
- [ ] AC#8: Frontend tests pass with the grid-only data flow, and `mergeManifestsAndGrid` is deleted.
