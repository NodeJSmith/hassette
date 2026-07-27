# Design: DB-Backed App Manifests

**Date:** 2026-07-26
**Status:** approved
**Scope-mode:** expand
**Research:** /tmp/claude-mine-define-research-qjFsPm/brief.md

## Problem

The dashboard app grid and apps list are driven solely by in-memory manifests (`AppRegistry._manifests`), creating two problems:

1. **Seed DBs are broken.** A seeded telemetry database with no running hassette instance produces an empty apps page because the spine comes from `runtime.get_all_manifests_snapshot()`, which reads from memory. The `seed_db.py` scenarios generate listeners, jobs, and executions keyed by `app_key`, but no mechanism persists the app metadata that the web layer needs to list them.

2. **Dual source of truth.** App identity lives in two places: in-memory config (parsed from `hassette.toml`) and DB telemetry (registration tables keyed by `app_key`). These must stay in sync, but nothing enforces that. Apps removed from config still have telemetry rows; apps added to config have no DB presence until their first handler fires.

The per-app detail page's telemetry sub-endpoints work correctly for any `app_key` because they query the DB directly — the gap is only in the list/grid views that iterate the manifest spine.

## Goals

- The telemetry DB is the single source of truth for which apps exist and their static metadata.
- Seed DBs produce working dashboards without a running hassette instance.
- Web routes for the dashboard grid and apps list query DB for the app spine.
- The per-app detail manifest endpoint returns data for DB-only apps (currently 404s).
- Frontend consumes a single server-side merged response — no client-side `mergeManifestsAndGrid`.

## Non-Goals

- **Full removal of `AppRegistry._manifests`** — still needed for runtime app loading, config resolution, and `AppFactory`. The in-memory dict remains but the web layer stops reading from it for list/grid views. Phase 2 work.
- **App lifecycle history** — tracking when apps were loaded/unloaded/failed over time. Separate concern.
- **App config versioning** — tracking config changes across sessions.
- **Cross-session comparisons** — "this app was healthy last session but failing now."
- **Per-instance grain** — the table keys on `app_key`, not `(app_key, instance_index)`. A migration to compound key is likely but separate.

## User Scenarios

### Developer: Seed DB workflow
- **Goal:** Open the dashboard against a seeded DB and see app data
- **Context:** Developing/demoing hassette, no live HA instance

#### View seeded apps on dashboard

1. **Run `seed_db.py --scenario healthy`**
   - Sees: script output confirming DB created
   - Then: DB file written with app manifests, listeners, jobs, executions

2. **Start hassette pointed at the seeded DB (or view via the web UI)**
   - Sees: dashboard app grid showing all seeded apps with status "stopped", telemetry data populated
   - Decides: click an app to drill into detail
   - Then: per-app detail page renders with historical telemetry, no 404

### Operator: Historical app visibility
- **Goal:** See apps that were loaded in a previous session but aren't in the current config
- **Context:** Troubleshooting, config change, or migration

#### View removed app's historical data

1. **Open dashboard after removing an app from config**
   - Sees: removed app still appears in the grid with its historical telemetry, distinguishable from currently-configured apps
   - Then: can click through to the detail page for full telemetry history

## Functional Requirements

- **FR#1** App manifest metadata (class name, display name, filename, enabled, autostart, auto-loaded) survives process restarts and is available to the web UI without a running hassette instance.
- **FR#2** The dashboard app grid (`GET /telemetry/dashboard/app-grid`) includes apps that have historical telemetry data, even if they are not currently loaded in the running config.
- **FR#3** The apps list (`GET /apps/manifests`) includes apps that have historical telemetry data, even if they are not currently loaded in the running config.
- **FR#4** The per-app manifest endpoint (`GET /apps/{app_key}/manifest`) returns manifest data for any app with persisted metadata, regardless of whether it is currently loaded. It no longer returns 404 for historically-known apps.
- **FR#5** When hassette is running, manifest entries display accurate runtime status (running/stopped/failed/blocked/disabled) and instance information reflecting the live state of each app.
- **FR#6** When hassette is not running (seed DB scenario), all apps show status "stopped" with zero instances.
- **FR#7** The dashboard grid and apps list endpoints return 503 when the telemetry store is unavailable.
- **FR#8** Seed DB scenarios include app manifest data so seeded dashboards show apps with correct metadata (class name, display name, etc.) without requiring a running hassette instance.
- **FR#9** The dashboard grid response includes app manifest metadata (class name, filename, enabled, autostart, auto-loaded, block reason, instances) alongside telemetry data, so the apps page can consume a single endpoint without client-side merging.
- **FR#10** Apps removed from the running config but with existing historical data remain visible in the dashboard with their telemetry history.
- **FR#11** The per-app manifest endpoint (`GET /apps/{app_key}/manifest`) returns 503 when the telemetry store is unavailable, distinguishing DB failure from a genuine 404 (app_key not found).

## Edge Cases

- **DB unavailable at startup**: Spine queries return 503. The dashboard is fully dependent on DB availability — this is a deliberate posture change (the DB is an integral component, not optional).
- **App in config but not yet persisted (boot)**: `set_apps_configs()` runs synchronously in `__init__`, before the deferred upsert in `bootstrap_apps()`. However, this window is not reachable through web requests — `WebApiService` transitively depends on `AppHandler`, so uvicorn cannot serve requests until after `AppHandler.after_initialize()` runs, which is after `bootstrap_apps()` (including the upsert) has completed. No race exists at boot.
- **Hot-reload race (the real window)**: During a hot-reload, the web server is already live. The reload-path upsert must land inside `refresh_config()`, immediately after `set_apps_configs()` updates the in-memory registry and before `apply_changes()` begins stopping/restarting app instances. This ensures a live request during reload sees consistent metadata + status. The window between `set_apps_configs()` and the upsert completing is narrow (< 20 manifest writes), and a request in that window would see new in-memory status with stale DB metadata — self-correcting on the next request after the upsert completes.
- **App removed from config**: Its `app_manifests` row stays in the DB. Status is derived as "stopped" (no in-memory running/failed/blocked state). The app remains visible in the grid with historical telemetry.
- **Stale DB data after config change**: On reload, the upsert updates static fields (class_name, display_name, etc.) to match the new config. The DB is always eventually consistent with the config within the same lifecycle event.
- **Seed DB with no running hassette**: All fields come from DB. Runtime-only fields default to safe values: `status="stopped"`, `instance_count=0`, `instances=[]`, `block_reason=None`, `error_message=None`.
- **Hot reload**: `set_apps_configs()` is called again. The upsert updates existing rows and inserts new ones. The reload path runs async (from the file-watcher handler), so `DatabaseService.submit()` is available.

## Acceptance Criteria

- **AC#1** (FR#1) After hassette boots with apps configured, `GET /apps/manifests` returns entries for each configured app with correct class_name, display_name, filename, enabled, autostart, and auto_loaded fields.
- **AC#2** (FR#2, FR#3) Against a seed DB with pre-populated app data, `GET /telemetry/dashboard/app-grid` and `GET /apps/manifests` return entries for all seeded apps — verifiable by running the seed script then hitting the endpoints.
- **AC#3** (FR#4) `GET /apps/{app_key}/manifest` returns 200 with manifest data for an app_key that exists only in historical data (not in the running config) — verifiable via integration test.
- **AC#4** (FR#5) When hassette is running with apps in various states, the dashboard grid shows correct runtime status for each app (running apps show "running", failed apps show "failed", etc.) — verifiable via integration test with a test harness.
- **AC#5** (FR#6) Against a seed DB with no running hassette, all apps show status "stopped" with `instance_count: 0` — verifiable by running the seed script and querying the endpoints.
- **AC#6** (FR#7) When the telemetry store is unavailable, `GET /telemetry/dashboard/app-grid` and `GET /apps/manifests` return HTTP 503 — verifiable via integration test.
- **AC#7** (FR#8) `seed_db.py --scenario healthy` produces a database where the dashboard endpoints return all scenario apps with correct metadata — verifiable by running the seed script and querying the endpoints.
- **AC#8** (FR#9) The dashboard grid response includes manifest metadata fields (class_name, filename, enabled, autostart, auto_loaded, block_reason, instances) and the apps page consumes it without a separate manifests fetch or client-side merge — verifiable by confirming `mergeManifestsAndGrid` is deleted and frontend tests pass.
- **AC#9** (FR#10) An app removed from config but with existing historical telemetry still appears on the dashboard with its telemetry data — verifiable via integration test.
- **AC#10** (FR#1) After a hot-reload with changed config (e.g., updated display_name), the next `GET /apps/manifests` response reflects the updated metadata — verifiable via integration test.
- **AC#11** (FR#11) When the telemetry store is unavailable, `GET /apps/{app_key}/manifest` returns HTTP 503 (not 404) — verifiable via integration test.
- **AC#12** (FR#10) Both `GET /telemetry/dashboard/app-grid` and `GET /apps/manifests` include `in_current_config: bool` for each app entry. Apps in the current config return `true`; DB-only/removed apps return `false` — verifiable via integration test.

## Key Constraints

- Do not persist runtime status (`running`/`failed`/`blocked`/`disabled`/`stopped`) to the DB. Status is always derived at query time — from in-memory state when hassette is running, from "stopped" default when not.
- Do not persist `app_config` to `app_manifests`. App config is arbitrary user data, already exposed separately via `GET /apps/{app_key}/config` with masking. Mixing it into the manifest table conflates metadata and user data.
- Do not persist `app_dir`, `full_path`, or `cache_key`. `app_dir` has no consumer in any response model. `full_path` is derivable and environment-specific. `cache_key` is a runtime override concern.
- The manifest upsert must NOT be called from `AppHandler.__init__()` or `AppLifecycleService.set_apps_configs()` when invoked during construction. `DatabaseService.submit()` raises `RuntimeError` if called before `on_initialize()` (write queue is `None`). Defer to `bootstrap_apps()` or `after_initialize()`.
- `only_apps` stays purely in-memory. It is session-specific CLI state (`--app` flag) that does not belong in the manifest table. Routes that include `only_apps` in responses source it from `AppRegistry` during the overlay, not from DB.

## Dependencies and Assumptions

- The telemetry DB is treated as an integral component. DB unavailability means degraded system operation, not silent fallback.
- `DatabaseService` is always initialized before `AppHandler.on_initialize()` runs — guaranteed by the Phase 1 / Phase 2 startup ordering in `Hassette.run_forever()` and transitively via `BusService`/`SchedulerService` `depends_on`.
- No new external dependencies. All infrastructure (write queue, query service, migration runner, seed context) exists.

## Architecture

### DB schema: `app_manifests` table

New migration `011.sql` adds the table:

```sql
CREATE TABLE IF NOT EXISTS app_manifests (
    id          INTEGER PRIMARY KEY,
    app_key     TEXT NOT NULL UNIQUE,
    class_name  TEXT NOT NULL,
    display_name TEXT NOT NULL,
    filename    TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    autostart   INTEGER NOT NULL DEFAULT 1,
    auto_loaded INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

Natural key: `app_key` (UNIQUE constraint). `created_at`/`updated_at` support retention and debugging. No `session_id` FK — this is a snapshot table where every upsert overwrites in place, so a session FK would only reflect the most recent session and misleadingly suggest history tracking the schema doesn't provide. Phase 2 lifecycle history will require a different table shape.

The UPSERT follows the existing `register_listener`/`register_job` pattern: `INSERT ... ON CONFLICT(app_key) DO UPDATE SET class_name=excluded.class_name, ... RETURNING id`. The `DO UPDATE SET` clause must explicitly include `updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')` — column `DEFAULT` expressions only fire on `INSERT`, not on `DO UPDATE SET`, so omitting this would silently freeze `updated_at` at the first insert's value.

### Persist trigger

The upsert is triggered from two call sites:

1. **Initial load** — inside `AppLifecycleService.bootstrap_apps()` (`app_lifecycle_service.py`), after `set_apps_configs()` has populated the in-memory registry and before apps are started. At this point `DatabaseService` is guaranteed ready (Phase 1 startup ordering). Each manifest upsert is isolated with per-item error handling (try/except that logs a warning and continues) and an explicit timeout, matching the fault-isolation patterns already used later in the same file (`start_apps()` uses `asyncio.gather(return_exceptions=True)`, `initialize_instances()` uses `anyio.fail_after()`). A failed manifest write degrades that one app's dashboard row — it never blocks app startup or crashes `AppHandler`.

2. **Hot reload** — inside `refresh_config()` in `AppLifecycleService`, immediately after `set_apps_configs()` updates the in-memory registry and before `apply_changes()` begins stopping/restarting app instances. This ordering ensures web requests during the reload see consistent metadata + status. This path runs async (from the file-watcher), so `DatabaseService.submit()` is available.

Both paths upsert the full manifest set with per-item isolation — each manifest's `submit()` call is wrapped in try/except with an explicit timeout. A failed write logs a warning and continues; the remaining manifests still get persisted. This matches the fault-isolation convention used later in the same file (`start_apps()` with `gather(return_exceptions=True)`, `initialize_instances()` with `fail_after()`). A partial write (e.g., manifests 1-6 succeed, #7 fails, 8-20 succeed) is self-correcting — the next boot re-upserts the full set, and in the interim one app shows slightly stale metadata, which is cosmetic rather than harmful. The full set is small (typically < 20 apps).

### Web route refactoring

Both `dashboard_app_grid` and `get_app_manifests` change from:
1. Get manifest spine from `runtime.get_all_manifests_snapshot()` (in-memory)
2. Look up DB telemetry as enrichment (Category C — silent-200 on DB failure)

To:
1. Query `app_manifests` table for the spine (Category B — 503 on DB failure)
2. Overlay in-memory runtime state (status, instances, block reasons) from `AppRegistry` when available
3. Enrich with telemetry from existing DB queries (summaries, activity buckets, last errors)

The overlay logic is owned by a single function — a new module-level function (e.g., `overlay_runtime_state(db_row, registry)`) co-located with `build_manifest_info()` in `app_registry.py`. All three routes (`dashboard_app_grid`, `get_app_manifests`, `get_app_manifest`) call this one function. This prevents the drift risk that `mergeManifestsAndGrid` had on the frontend — one code path, one derivation.

The function's logic:
- For each `app_key` from the DB spine, check `AppRegistry` for runtime state
- If found: extract only the **status derivation and instance data** from the in-memory registry (the priority logic: disabled > blocked > running > failed > stopped, plus the `instances` list, and `in_current_config = true`). Static metadata fields (class_name, display_name, etc.) come from the DB row, not from in-memory — the DB is the source of truth for metadata, the registry is the source of truth for live status.
- If not found (DB-only app): status = "stopped", instance_count = 0, instances = [], `in_current_config = false`
- A computed `in_current_config: bool` field is added to both `DashboardAppGridEntry` and `AppManifestResponse` (true if `app_key in registry.manifests`, false otherwise). This is derived at query time, not stored — consistent with the "don't persist runtime-derived data" principle. It enables the frontend to distinguish "removed from config" from "currently configured but stopped" across all consumers: apps page, sidebar navigation, command palette, logs page filter, and the app shell.
- `only_apps` is sourced from `AppRegistry` and attached to the list response, not from DB

The per-app manifest endpoint (`GET /apps/{app_key}/manifest`) changes similarly: query DB by `app_key` instead of `registry.get_manifest_snapshot()`. Returns 200 with DB data even if no manifest is loaded. Returns 404 only if the `app_key` doesn't exist in the DB at all.

### Category C → B transition (spine only)

The new DB spine query is Category B (503 via `db_degrades_to`) — the entries loop cannot run without it. The three existing enrichment queries (`get_all_app_summaries`, `get_per_app_activity_buckets`, `get_per_app_last_errors`) remain Category C — each independently caught, degrading to empty defaults while the response continues at 200. This preserves the existing per-query fault isolation: a flaky "last errors" query degrades that one enrichment to zeroed stats, not the entire grid to 503.

Concretely, the route uses two blocks:
1. `with db_degrades_to(response):` wrapping only the spine query + overlay (Category B — 503 if spine unavailable)
2. The existing per-query `try/except TelemetryUnavailableError` blocks for each enrichment call (Category C — unchanged)

The `web/CLAUDE.md` classification table must be updated: the new spine query is a new Category B site; existing enrichment sites #9-#12 stay Category C.

### RuntimeQueryService changes

`RuntimeQueryService.get_all_manifests_snapshot()` is no longer the spine source for web routes. The web routes query DB directly via `TelemetryQueryService`. `RuntimeQueryService` still provides in-memory state for the overlay (status derivation, instance data, `only_apps`) via existing methods like `get_app_status_snapshot()` or a new lightweight accessor.

### Grid response extension

`DashboardAppGridEntry` (`web/models.py`) is extended with manifest metadata fields that the apps page currently sources from the separate manifests endpoint: `class_name`, `filename`, `enabled`, `auto_loaded`, `autostart`, `block_reason`, `instances`, `error_message`, `error_traceback`. These are populated from the DB spine + in-memory overlay in the same `dashboard_app_grid` route handler. This is not the same as Alternative C (removing the manifests endpoint) — both endpoints continue to exist, but the grid endpoint becomes self-sufficient for the apps page's needs.

### Frontend simplification

- `mergeManifestsAndGrid()` in `frontend/src/utils/app-data.ts` is deleted. The `AppRow` type is rebuilt to match the extended `DashboardAppGridEntry` response shape directly.
- `frontend/src/pages/apps.tsx` consumes only the grid endpoint for the apps table. The manifests endpoint continues to serve the per-app detail page.
- `frontend/src/hooks/use-manifests.ts` is evaluated for removal from the apps page — it may still be needed by the detail page.
- The apps page gains a 503 error state for when the DB is unavailable. Currently, the manifest spine is always available (in-memory), so there's no "unavailable" state. After this change, DB failure means no apps list. Use the existing error-state pattern from other pages that handle 503.
- WebSocket real-time updates are unaffected — WS only pushes per-instance status deltas (`app_status_changed`), never manifest lists. The `appStatus` signal overlay continues to work on top of the REST-fetched data.

### Seed DB integration

`SeedContext` in `scripts/seed_db.py` gains an `add_app_manifest()` method following the existing `add_listener()`/`add_job()` pattern. Each scenario's app setup calls this before adding listeners/jobs. The manifest row uses the same `app_key`, `class_name`, and `display_name` values that the scenario already defines for its listeners/jobs.

## Implementation Preferences

- New migration file `011.sql` — follow the existing numbered migration pattern with `BEGIN IMMEDIATE` / `COMMIT`.
- Repository method `upsert_app_manifest()` uses `INSERT ... ON CONFLICT(app_key) DO UPDATE SET ... RETURNING id`, matching the listener/job UPSERT pattern exactly.
- Manifest upserts use blocking `submit()` through the DB write queue, not fire-and-forget `enqueue()` — consistent with how listener/job registration works.
- Query functions use the existing `TelemetryQueryService.execute()` context manager with timeout and `STORAGE_ERRORS → TelemetryUnavailableError` translation.
- A `manifest_insert_params()` function (matching `listener_insert_params()`/`job_insert_params()`) converts `AppManifest` to a parameterized dict for the upsert.
- `db_degrades_to(response)` for the Category B spine queries — not inline try/except.

## Replacement Targets

- **`runtime.get_all_manifests_snapshot()` as spine source** in `web/routes/telemetry.py:dashboard_app_grid` and `web/routes/apps.py:get_app_manifests` — replaced by DB query on `app_manifests`. The `RuntimeQueryService` method itself is not deleted (other consumers may exist), but the web routes stop calling it for the spine.
- **`registry.get_manifest_snapshot(app_key)` in `web/routes/apps.py:get_app_manifest`** — replaced by DB query. The registry method itself is not deleted.
- **`mergeManifestsAndGrid()` in `frontend/src/utils/app-data.ts`** — deleted entirely. The backend provides merged data.
- **Category C classification for sites #9-#12** in `web/CLAUDE.md` — replaced with Category B classification.

## Migration

- **Schema**: New `app_manifests` table added via `011.sql`. Additive DDL — no existing table modifications.
- **Existing data**: No migration of existing data needed. On first boot after upgrade, `bootstrap_apps()` populates `app_manifests` from the current config. Historical app data (from previous sessions) only appears in the DB after the first post-upgrade boot where those apps were configured.
- **Reversibility**: Drop the table and revert the code. No impact on existing tables (`listeners`, `scheduled_jobs`, `executions`, `sessions`).
- **Seed DB**: Existing seed DBs generated before this change won't have `app_manifests` rows. The migration runner handles this — `011.sql` runs on first open, creating the empty table. Seed scenarios should be regenerated to include manifest data.

## Convention Examples

### UPSERT with natural key (listener registration)

**Source:** `src/hassette/core/telemetry/repository.py:298-360`

```python
async def register_listener(self, registration: ListenerRegistration) -> int:
    db = self._db_service.db
    cursor = await db.execute(
        """
        INSERT INTO listeners (app_key, instance_index, handler_method, topic, ...)
        VALUES (:app_key, :instance_index, :handler_method, :topic, ...)
        ON CONFLICT(app_key, instance_index, name, topic)
        DO UPDATE SET
            debounce = excluded.debounce,
            ...
            retired_at = NULL,
            cancelled_at = NULL
        RETURNING id
        """,
        listener_insert_params(registration),
    )
    row = await cursor.fetchone()
    await db.commit()
    return row[0]
```

### Query with error translation

**Source:** `src/hassette/core/telemetry/query_service.py:65-81`

```python
@contextlib.asynccontextmanager
async def execute(self, query: str, params: dict[str, Any] | None = None) -> AsyncIterator[aiosqlite.Cursor]:
    try:
        async with asyncio.timeout(self.hassette.config.database.read_timeout_seconds):
            async with self._db.execute(query, params) as cursor:
                yield cursor
    except STORAGE_ERRORS as exc:
        raise TelemetryUnavailableError(str(exc)) from exc
```

### Category B route with db_degrades_to

**Source:** `src/hassette/web/routes/telemetry.py` (existing Category B pattern, function `app_health`)

```python
@router.get("/telemetry/app/{app_key}/health")
async def app_health(..., response: Response) -> AppHealthResponse:
    result = AppHealthResponse()  # pre-initialized failure default
    with db_degrades_to(response):
        raw = await telemetry.get_app_health_aggregates(app_key=app_key, ...)
        result = AppHealthResponse(**raw)
    return result
```

### Seed context add_* pattern

**Source:** `scripts/seed_db.py:218-237`

```python
def add_listener(
    self,
    registration: ListenerRegistration,
    *,
    retired_at: float | None = None,
    cancelled_at: float | None = None,
) -> int:
    params = listener_insert_params(registration)
    params["retired_at"] = retired_at
    params["cancelled_at"] = cancelled_at
    sql = _build_insert_sql("listeners", params, returning=True)
    return insert_row(self.cursor, sql, params)
```

Note: `SeedContext` uses **synchronous** `sqlite3.Cursor` via the `insert_row()`/`_build_insert_sql()` helpers, not async `aiosqlite`. The `add_app_manifest()` method should follow this same synchronous pattern.

### Mapper: dataclass to Pydantic response

**Source:** `src/hassette/web/mappers.py:71-88`

```python
def app_manifest_response_from(manifest: AppManifestInfo) -> AppManifestResponse:
    return AppManifestResponse(
        app_key=manifest.app_key,
        class_name=manifest.class_name,
        display_name=manifest.display_name,
        ...
        status=cast("ManifestStatus", manifest.status),
    )
```

## Alternatives Considered

### A: Union in-memory + DB keys at the web route level (no new table)

Instead of persisting manifests, the web routes would query existing DB tables (`listeners`, `scheduled_jobs`) for distinct `app_key` values and union them with the in-memory manifest set. Synthetic entries would have placeholder metadata (`class_name="Unknown"`, `display_name=app_key`).

**Rejected because:** While the chosen design also merges at read time (DB spine + in-memory overlay), Alternative A doesn't achieve the independently-valued goals of FR#1 (metadata survives restarts) and FR#4 (per-app detail page works for historical apps). A label-only table (`app_key` + `display_name`) would fix the placeholder-text cosmetic issue but wouldn't persist the full metadata needed for the detail page manifest endpoint to return meaningful data for DB-only apps. The full `app_manifests` table is justified by these requirements, not just by the seed-DB UX concern.

### B: Persist runtime status in the DB

Add a `status` column to `app_manifests` and update it on every state transition.

**Rejected because:** Status derivation depends on four in-memory dicts with priority logic (`disabled > blocked > running > failed > stopped`). Persisting it means either writing to DB on every transition (60+ writes during normal boot for 20 apps with 2 instances) or accepting staleness. The overlay approach (derive at query time) avoids both problems and is consistent with how status works today.

### C: Remove the manifests endpoint entirely, make grid the only endpoint

Instead of keeping two endpoints, remove the manifests endpoint and serve everything from the grid.

**Rejected:** The manifests endpoint serves the per-app detail page and may serve other consumers. The chosen approach is a middle path: extend `DashboardAppGridEntry` with manifest metadata fields so the apps page only needs the grid endpoint, while keeping the manifests endpoint alive for the detail page and other consumers.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/core/test_app_registry.py` — `TestAppRegistryGetFullSnapshot`: tests currently verify that `get_full_snapshot()` produces correct `AppManifestInfo` entries from in-memory manifests. These tests continue to pass (the in-memory registry behavior doesn't change), but new tests are needed for the DB-backed path.
- `tests/unit/web/test_mappers.py` — `test_app_manifest_list_response_from_*`: tests verify mapper behavior from `AppFullSnapshot`. If the mapper signature changes to accept DB rows instead of `AppFullSnapshot`, these tests need updating.
- `tests/integration/web_api/test_telemetry.py` — `TestTelemetryDashboard::test_app_grid_returns_per_app_health`: currently asserts default mock shape (manifest-sourced). Needs updating for DB-sourced spine.
- `tests/integration/test_apps.py` — manifest endpoint tests assume in-memory registry is the source. Need updating for DB source.
- `tests/integration/test_dashboard_without_ha.py` — exercises `get_full_snapshot()` in a real boot. May need updating depending on whether the test validates the web response shape.
- Frontend tests: `frontend/src/pages/apps.test.tsx`, `frontend/src/hooks/use-manifests.test.ts` — tests that mock or consume the manifests endpoint separately from the grid endpoint need updating to reflect the simplified data flow. Note: `mergeManifestsAndGrid()` has no dedicated test file — it is untested.

### New Test Coverage

- **Unit**: `upsert_app_manifest()` repository method — verify UPSERT creates new row, updates existing row on conflict, preserves `id` across updates (FR#1).
- **Unit**: `manifest_insert_params()` — verify correct parameter dict from `AppManifest` input. Include a schema-parity assertion: `set(manifest_insert_params(...).keys())` must match the UPSERT column set, so a field added to `AppManifest` without a corresponding DB column change fails loudly.
- **Unit**: New query function — verify correct SQL and row-to-model mapping.
- **Integration**: Manifest persistence on boot — verify `app_manifests` rows appear after `bootstrap_apps()` completes (FR#1, AC#1).
- **Integration**: Dashboard grid with DB-only apps — seed DB rows without loading manifests, verify grid includes them (FR#2, AC#2).
- **Integration**: Apps list with DB-only apps — same as above for the manifest list endpoint (FR#3, AC#2).
- **Integration**: Per-app manifest for DB-only app — verify 200 instead of 404 (FR#4, AC#3).
- **Integration**: Runtime status overlay — verify running apps show correct status when both DB and in-memory state exist (FR#5, AC#4).
- **Integration**: DB unavailable — verify 503 response for grid, manifest list, and per-app manifest endpoints (FR#7, FR#11, AC#6, AC#11).
- **Integration**: Hot reload upsert — verify DB rows update after config change (FR#1, AC#10).
- **Unit (seed)**: `SeedContext.add_app_manifest()` — verify row insertion and correct field mapping (FR#8, AC#7).
- **Unit (seed)**: Seed scenario parity assertion — for every scenario, assert `set(app_manifests.app_key) ⊇ set(listeners.app_key) ∪ set(scheduled_jobs.app_key)` to catch forgotten `add_app_manifest()` calls that would silently reproduce the exact bug this design fixes.
- **Frontend**: Apps page renders without `mergeManifestsAndGrid` (FR#9, AC#8).
- **Frontend**: Apps page 503 error state when DB unavailable.

### Tests to Remove

- No existing tests to remove — `mergeManifestsAndGrid()` is untested (no `app-data.test.ts` exists). The function is deleted as part of the frontend simplification.

## Documentation Updates

- **`web/CLAUDE.md`**: Update the category classification table — sites #9-#12 change from Category C to Category B. Update the site count summary.
- **`CLAUDE.md` (project root)**: Update the Architecture section's `AppRegistry` description if the web layer's relationship to it changes significantly.
- **Docs site**: If any docs page describes the dashboard data flow or app monitoring architecture, update it to reflect DB-backed manifests.

## Impact

### Changed Files

- **create** `src/hassette/migrations_sql/011.sql` — `app_manifests` table DDL
- **modify** `src/hassette/core/telemetry/repository.py` — add `upsert_app_manifest()`, `manifest_insert_params()`
- **modify** `src/hassette/core/telemetry/query_service.py` or create new query module — add manifest query functions
- **modify** `src/hassette/core/app_lifecycle_service.py` — add manifest upsert call in `bootstrap_apps()` and reload path
- **modify** `src/hassette/web/routes/telemetry.py` — refactor `dashboard_app_grid` to use DB spine + overlay
- **modify** `src/hassette/web/routes/apps.py` — refactor `get_app_manifests` and `get_app_manifest` to use DB spine
- **modify** `src/hassette/web/mappers.py` — add/modify mappers for DB-row-to-response conversion
- **modify** `src/hassette/web/models.py` — adjust response models if field optionality changes
- **modify** `src/hassette/web/CLAUDE.md` — update category classification table
- **modify** `src/hassette/schemas/app_snapshots.py` — may need adjustments to `AppManifestInfo` or new DB-row dataclass
- **modify** `src/hassette/core/runtime_query_service.py` — adjust or add methods for overlay data access
- **modify** `scripts/seed_db.py` — add `add_app_manifest()` to `SeedContext`, update all scenarios
- **modify** `frontend/src/pages/apps.tsx` — consume server-side merged data, add 503 error state
- **delete** `frontend/src/utils/app-data.ts` `mergeManifestsAndGrid()` — or the entire file if no other exports remain
- **modify** `frontend/src/hooks/use-manifests.ts` — evaluate for removal or simplification
- **modify** `scripts/export_schemas.py` + generated type files — regenerate after model changes
- **modify** multiple test files — see Test Strategy above

### Behavioral Invariants

- Per-app detail page telemetry sub-endpoints (`/telemetry/app/{app_key}/health`, `/listeners`, `/activity`, `/jobs`) continue to work exactly as today — they query DB by `app_key` and are unaffected by this change.
- WebSocket real-time status updates (`app_status_changed`) continue to work — they push per-instance deltas and don't depend on the manifest list.
- `AppRegistry` continues to function identically for runtime use (app loading, config resolution, `AppFactory`).
- `only_apps` CLI filter continues to work — sourced from in-memory registry, not DB.
- The `GET /apps` endpoint (status endpoint, not manifest endpoint) is unaffected — it uses `get_app_status_snapshot()` which is separate from the manifest flow.

### Blast Radius

- **Frontend apps page**: Most visible change — data source shifts from client-side merge to server-side. Error handling changes (new 503 state).
- **Sidebar, command palette, logs filter, app shell**: All consume `GET /apps/manifests` via `useManifests()`. The new `in_current_config` field lets these surfaces distinguish removed apps from live ones. Frontend may need to filter or badge removed apps in navigation/search.
- **Seed DB consumers**: All seed scenarios need updating to include `add_app_manifest()` calls. Existing seed DBs generated before this change will have an empty `app_manifests` table (migration creates it, but no rows).
- **System tests**: Any system test that validates dashboard/apps-list responses may need updating for the new response shape and 503 behavior.
- **E2E tests**: Playwright tests that navigate the apps page may see different behavior if they test error states.

## Open Questions

None — all questions resolved during discovery and investigation.
