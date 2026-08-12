---
task_id: "T05"
title: "Frontend degraded status and remaining test migration"
status: "done"
depends_on: ["T03", "T04"]
implements: ["AC#6", "AC#8"]
---

## Summary

Add `"degraded"` to the frontend status maps, filter options, and type union. Update all remaining test files that weren't covered by T01-T04: the `get_apps_by_key` → `get_running_apps` rename across integration/system tests, `AppStatusSnapshot` field references, `ManifestStatus` literal tests, `AppManifestListResponse` test constructions, e2e mock fixture cleanup, and frontend test factories/handlers. This is the final task — after it, all tests should pass and lint should be clean.

## Target Files

- modify: `frontend/src/utils/status.ts`
- modify: `frontend/src/pages/apps.tsx`
- modify: `frontend/src/test/factories.ts`
- modify: `frontend/src/test/handlers.ts`
- modify: `frontend/src/hooks/use-manifests.test.ts`
- modify: `tests/integration/test_app_factory_lifecycle.py`
- modify: `tests/system/test_app_lifecycle.py`
- modify: `tests/e2e/mock_fixtures.py`
- read: `design/specs/096-registry-instance-unification/design.md`

## Prompt

### Frontend status maps

In `frontend/src/utils/status.ts`:
- Add `"degraded"` to the `AppStatus` type union
- Add `["degraded", "warning"]` to `APP_STATUS_MAP`
- Add `["degraded", "warn"]` to `STATUS_KIND_MAP`

In `frontend/src/pages/apps.tsx`:
- Add `"degraded"` to `FILTER_OPTIONS` array (line 31)
- Add `degraded: 0` to the fixed-key `statusCounts` initializer (line 64). The dynamic builder at line 197 already handles any status value via `??`.
- Add a `"degraded"` cell to the summary `cells` array (lines 78-86) — `statusCounts` is computed locally from per-app manifest status, NOT from `AppManifestListResponse` count fields. No `status_counts` nesting change needed here.

### Frontend test files

In `frontend/src/test/factories.ts`:
- Update `AppManifestListResponse` construction to use `status_counts: { running: N, failed: N, ... }` instead of individual top-level count fields

In `frontend/src/test/handlers.ts`:
- Same update for mock response construction

In `frontend/src/hooks/use-manifests.test.ts`:
- Same update for response construction in tests

### Backend test migration (gap check items)

In `tests/integration/test_app_factory_lifecycle.py`:
- Rename all `get_apps_by_key` references to `get_running_apps` (~20+ call sites)
- Update `snapshot.running`, `snapshot.failed`, `snapshot.running_count`, `snapshot.failed_count`, `snapshot.running_apps`, `snapshot.failed_apps` references to use `.instances` and the computed properties (the properties still exist, so count/set access is unchanged — only direct `.running`/`.failed` list access needs updating)

In `tests/system/test_app_lifecycle.py`:
- Rename `registry.get_apps_by_key()` to `registry.get_running_apps()` (line 43)

In `tests/e2e/mock_fixtures.py`:
- Remove the orphaned `registry.iter_all_instances.return_value = [...]` mock (line ~870) — method is deleted
- Rename `registry.get_apps_by_key` mock (line ~873) to `registry.get_running_apps`

### Verification

After all changes, run `cd frontend && npm run build` to verify the frontend compiles, and run frontend tests with `cd frontend && npm run test`.

## Focus

- The `FILTER_OPTIONS` array in `apps.tsx` determines what the user can filter by in the apps page dropdown. `"degraded"` should appear between `"failed"` and `"stopped"` to match the priority order.
- The `cells` array in `apps.tsx` builds the summary stat badges at the top of the page. `statusCounts` is computed **locally** from per-app `appLiveStatus` — it does NOT read from `AppManifestListResponse`'s count fields. The `status_counts` field migration (T03) affects the API wire format but `apps.tsx` never consumes those API-level counts. The only change needed here is adding `"degraded"` to the local `statusCounts` initializer and the `cells` array.
- `tests/integration/test_app_factory_lifecycle.py` is the heaviest migration target (~20+ `get_apps_by_key` call sites plus snapshot field access). All changes are mechanical renames.
- `INACTIVE_STATUSES` in `status.ts` does not need `"degraded"` — degraded apps have at least one running instance, so they're not inactive.

## Verify

- [ ] AC#6: `prek -a && prek pyright -a --stage pre-push` passes with no errors — final cross-cutting type/lint verification after all tasks
- [ ] AC#8: Frontend `statusToVariant("degraded")` returns `"warning"` and `statusToKind("degraded")` returns `"warn"` — verified by running frontend tests
