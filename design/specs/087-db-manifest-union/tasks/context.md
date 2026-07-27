# Context: DB-Backed App Manifests

## Problem & Motivation

The dashboard app grid and apps list are driven solely by in-memory manifests (`AppRegistry._manifests`), making apps with telemetry data but no loaded manifest invisible. This breaks seed DB workflows entirely — a seeded database with no running hassette produces an empty apps page. It also creates a dual source of truth: app identity lives in both in-memory config and DB telemetry, with nothing enforcing sync. This design persists app manifest metadata to a new `app_manifests` DB table, making the DB the single source of truth for which apps exist. Web routes query the DB for the app spine and overlay in-memory runtime state (status, instances) at query time.

## Visual Artifacts

None.

## Key Decisions

1. **No runtime status in DB** — status is derived at query time from in-memory state (when running) or defaults to "stopped" (seed DB). Avoids staleness and unnecessary DB writes on every state transition.
2. **Per-item upsert isolation** — each manifest write is isolated with try/except + timeout. A failed write degrades one app's dashboard row, never blocks app startup. Matches `start_apps()`/`initialize_instances()` fault-isolation conventions.
3. **Spine query is Category B, enrichment stays Category C** — the DB spine query uses `db_degrades_to` (503 on failure), while the three existing enrichment queries remain independently caught with empty defaults (200 continues). Preserves per-query fault isolation.
4. **Single overlay function** — `overlay_runtime_state()` co-located with `build_manifest_info()` in `app_registry.py`. All three web routes call this one function to prevent drift.
5. **`in_current_config` computed field** — added to both `DashboardAppGridEntry` and `AppManifestResponse` (true if `app_key in registry.manifests`). Distinguishes "removed from config" from "currently stopped."
6. **Grid response extended** — `DashboardAppGridEntry` gains manifest metadata fields so the apps page needs only the grid endpoint. The manifests endpoint stays alive for the detail page and other consumers.
7. **Table keyed on `app_key`** — per-app grain. A migration to `(app_key, instance_index)` compound key is likely but separate (Non-Goal).
8. **No `session_id`, no `app_dir`** — `session_id` misleadingly suggests history tracking the schema can't provide. `app_dir` has no consumer in any response model.
9. **`updated_at` must be explicitly refreshed** — `DO UPDATE SET` must include `updated_at = strftime(...)` because column DEFAULT only fires on INSERT, not on UPDATE.

## Constraints & Anti-Patterns

- Do NOT persist runtime status to the DB.
- Do NOT persist `app_config`, `app_dir`, `full_path`, or `cache_key`.
- Do NOT call the manifest upsert from `AppHandler.__init__()` or `set_apps_configs()` during construction — `DatabaseService.submit()` raises `RuntimeError` before `on_initialize()`.
- Do NOT implement Non-Goals: full removal of `AppRegistry._manifests`, lifecycle history, config versioning, cross-session comparisons, per-instance grain.
- `only_apps` stays purely in-memory — not in the DB table.
- Do NOT wrap enrichment queries in `db_degrades_to` — they stay Category C with independent try/except.
- Do NOT use `enqueue()` (fire-and-forget) for manifest writes — use blocking `submit()`.

## Design Doc References

- `## Architecture → DB schema` — table DDL, UPSERT pattern, updated_at refresh
- `## Architecture → Persist trigger` — bootstrap_apps and refresh_config call sites, per-item isolation
- `## Architecture → Web route refactoring` — spine query + overlay + enrichment split
- `## Architecture → Category C → B transition` — which queries change category, which don't
- `## Architecture → Grid response extension` — which fields DashboardAppGridEntry gains
- `## Architecture → Frontend simplification` — what to delete, what to keep
- `## Architecture → Seed DB integration` — add_app_manifest pattern
- `## Implementation Preferences` — specific tooling and pattern decisions
- `## Replacement Targets` — code being replaced (not preserved alongside new code)
- `## Test Strategy` — existing tests to adapt, new coverage needed, tests to remove

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

Note: `SeedContext` uses **synchronous** `sqlite3.Cursor` via the `insert_row()`/`_build_insert_sql()` helpers, not async `aiosqlite`.

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
