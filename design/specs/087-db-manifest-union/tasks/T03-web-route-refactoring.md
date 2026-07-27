---
task_id: "T03"
title: "Refactor web routes to use DB spine and overlay"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#2", "FR#3", "FR#4", "FR#7", "FR#11", "AC#2", "AC#3", "AC#6", "AC#11"]
---

## Summary

Refactor the three manifest-consuming web routes (`dashboard_app_grid`, `get_app_manifests`, `get_app_manifest`) to query the `app_manifests` DB table for the spine instead of `AppRegistry._manifests`. Each route calls the `overlay_runtime_state()` function from T02. The spine query uses `db_degrades_to` (Category B, 503 on failure). Existing enrichment queries stay Category C (independent try/except). Includes integration tests for DB-only apps and 503 behavior.

## Target Files

- modify: `src/hassette/web/routes/telemetry.py`
- modify: `src/hassette/web/routes/apps.py`
- modify: `src/hassette/web/mappers.py`
- modify: `src/hassette/web/CLAUDE.md`
- read: `src/hassette/web/dependencies.py` (db_degrades_to pattern)
- read: `src/hassette/core/app_registry.py` (overlay_runtime_state from T02)
- read: `src/hassette/core/telemetry/query_service.py` (manifest query from T01)
- modify: `tests/integration/web_api/test_telemetry.py`
- modify: `tests/integration/test_apps.py`
- modify: `tests/integration/web_api/test_telemetry_unavailable_seam.py`

## Prompt

### `dashboard_app_grid` in `telemetry.py`

Refactor per the design doc's `## Architecture → Web route refactoring` and `## Architecture → Category C → B transition (spine only)`.

Current flow: `snapshot = runtime.get_all_manifests_snapshot()` → iterate `snapshot.manifests` → look up DB enrichment.

New flow:
1. Pre-initialize empty response default
2. `with db_degrades_to(response):` — query `app_manifests` table for all rows, call `overlay_runtime_state(db_rows, registry)` to get manifest entries with live status
3. The three enrichment queries (`get_all_app_summaries`, `get_per_app_activity_buckets`, `get_per_app_last_errors`) stay in their existing per-query `try/except TelemetryUnavailableError` blocks (Category C unchanged)
4. Build `DashboardAppGridEntry` for each overlaid manifest, enriching with telemetry data as before

The `only_apps` field on the list response is sourced from `AppRegistry` via `RuntimeQueryService`, not from DB.

### `get_app_manifests` in `apps.py`

Same spine-from-DB refactoring. The route currently calls `runtime.get_all_manifests_snapshot()` and maps through `app_manifest_list_response_from()`. Change to:
1. `with db_degrades_to(response):` — query all manifests, overlay runtime state
2. Map overlaid results to `AppManifestResponse` list
3. The `recent_invocations_1h` enrichment stays Category C (try/except)

### `get_app_manifest` in `apps.py`

Currently calls `registry.get_manifest_snapshot(app_key)` and returns 404 if None. Change to:
1. `with db_degrades_to(response):` — query single manifest by `app_key`, overlay runtime state
2. Return 200 with data if found in DB
3. Return 404 only if `app_key` doesn't exist in DB at all
4. On DB failure → 503 (via `db_degrades_to`)

### Mapper updates in `mappers.py`

Update `app_manifest_response_from()` and `app_manifest_list_response_from()` if their input type changes from `AppManifestInfo`/`AppFullSnapshot` to the overlay function's output. The overlay function returns `AppManifestInfo` (possibly extended with `in_current_config`), so the mapper may need minimal changes.

### `web/CLAUDE.md` classification table

Update: the new spine query is a new Category B site. Existing enrichment sites #9-#12 stay Category C. Update the count summary.

### Integration tests

- Test DB-only apps appear in dashboard grid response (seed manifest rows in DB without loading to registry)
- Test DB-only apps appear in manifests list response
- Test per-app manifest returns 200 for DB-only app (not 404)
- Test 503 when DB is unavailable for grid, manifests list, and per-app manifest
- Update existing `test_app_grid_returns_per_app_health` for the new DB-sourced spine

## Focus

- `db_degrades_to` is imported from `src/hassette/web/dependencies.py`. Read it to understand the context manager pattern.
- The spine query wraps only the DB read + overlay. Enrichment queries are OUTSIDE the `db_degrades_to` block.
- `test_telemetry_unavailable_seam.py` tests the 503 behavior — it may already test some of these endpoints but with the old Category C expectations. Update to expect 503 for the spine query.
- The route currently gets `runtime: RuntimeDep` for the snapshot. After this change, it also needs `telemetry: TelemetryDep` for the spine query and still needs `runtime` (or `registry` directly) for the overlay and `only_apps`.
- Mappers in `mappers.py` currently take `AppManifestInfo` / `AppFullSnapshot` — if the overlay returns the same types (just extended), mappers need minimal change. If it returns a different type, update mappers accordingly.
- `tests/integration/web_api/test_endpoints.py` may also need updates if it mocks `get_manifest_snapshot()`.

## Verify

- [ ] FR#2: Dashboard grid includes DB-only apps (verified by seeding DB manifest rows and checking grid response).
- [ ] FR#3: Apps list includes DB-only apps (same verification approach).
- [ ] FR#4: `GET /apps/{app_key}/manifest` returns 200 for a DB-only app_key (verified via integration test).
- [ ] FR#7: Dashboard grid and apps list return 503 when DB is unavailable (verified via integration test).
- [ ] FR#11: Per-app manifest returns 503 when DB is unavailable (not 404) (verified via integration test).
- [ ] AC#2: Against a seed DB, grid and manifests endpoints return all seeded apps.
- [ ] AC#3: Per-app manifest returns 200 with data for a DB-only app_key.
- [ ] AC#6: Grid and manifests list return HTTP 503 when telemetry store is unavailable.
- [ ] AC#11: Per-app manifest returns HTTP 503 (not 404) when telemetry store is unavailable.
