---
task_id: "T01"
title: "Add app_manifests table and repository methods"
status: "planned"
depends_on: []
implements: ["FR#1"]
---

## Summary

Create the `app_manifests` DB table via a new migration and add repository methods for upserting and querying manifest rows. This is the foundation — all other tasks depend on this table and these methods existing. Includes `manifest_insert_params()` for converting `AppManifest` to a parameterized dict, `upsert_app_manifest()` for the UPSERT, and query functions for reading manifests back (all apps and single app by key). Unit tests for all new functions are included.

## Target Files

- create: `src/hassette/migrations_sql/011.sql`
- modify: `src/hassette/core/telemetry/repository.py`
- modify: `src/hassette/core/telemetry/query_service.py`
- read: `src/hassette/core/telemetry/repository.py` (existing UPSERT pattern)
- read: `src/hassette/config/classes.py` (AppManifest fields)
- read: `src/hassette/migrations_sql/010.sql` (latest migration)
- read: `src/hassette/core/migration_runner.py` (migration pattern)
- create: `tests/unit/core/telemetry/test_manifest_repository.py`

## Prompt

Create the `app_manifests` DB table and repository layer. Follow the design doc's `## Architecture → DB schema` section.

### Migration file `011.sql`

Create `src/hassette/migrations_sql/011.sql` with `BEGIN IMMEDIATE` / `COMMIT` wrapping. The table schema:

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

The migration runner derives the schema version automatically from the filename (`011.sql` → version 11) and appends `PRAGMA user_version` itself — do NOT include a manual `PRAGMA user_version` statement in `011.sql`.

### Repository methods in `repository.py`

Add `manifest_insert_params(manifest: AppManifest) -> dict` — converts an `AppManifest` (from `src/hassette/config/classes.py`) to a parameter dict for the UPSERT. Fields: `app_key`, `class_name`, `display_name`, `filename`, `enabled` (as int), `autostart` (as int), `auto_loaded` (as int). Match the `listener_insert_params()` / `job_insert_params()` pattern exactly.

Add `upsert_app_manifest()` to `TelemetryRepository` — follows the `register_listener()` UPSERT pattern from `repository.py:298-360`. The `DO UPDATE SET` clause must include `updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')` explicitly (column DEFAULT only fires on INSERT).

### Query functions

Add to `TelemetryQueryService` (or a new module — follow the existing organization):
- `get_all_app_manifests() -> list[dict]` — `SELECT * FROM app_manifests` using the `execute()` context manager with timeout/error translation.
- `get_app_manifest(app_key: str) -> dict | None` — single-app lookup by app_key.

### Unit tests

Write tests in a new file `tests/unit/core/telemetry/test_manifest_repository.py`:
- `manifest_insert_params()` produces correct dict from an `AppManifest` input
- Schema-parity assertion: `set(manifest_insert_params(...).keys())` matches the UPSERT column set
- `upsert_app_manifest()` creates a new row and returns an id
- `upsert_app_manifest()` updates existing row on conflict (preserves id)
- `updated_at` is refreshed on conflict (not frozen at first insert)

## Focus

- The migration file numbering must be `011.sql` — confirm `010.sql` is the latest with `ls src/hassette/migrations_sql/`.
- `manifest_insert_params()` is a module-level function, not a method — matches `listener_insert_params()` at `repository.py:90-119`.
- Boolean fields (`enabled`, `autostart`, `auto_loaded`) must be stored as integers (SQLite has no boolean type) — cast with `int(manifest.enabled)` etc.
- The UPSERT conflict target is `(app_key)` — simpler than listener/job which use compound natural keys.
- `TelemetryRepository.__init__` takes `db_service: DatabaseService` — the upsert accesses `self._db_service.db` for the connection.
- The migration runner (`src/hassette/core/migration_runner.py`) auto-derives version from filename — no `HEAD_VERSION` constant to bump. Verify by reading the runner.

## Verify

- [ ] FR#1: `011.sql` creates the `app_manifests` table with all specified columns and the migration runner applies it successfully (verified by unit test calling `run_migrations` on a fresh DB).
