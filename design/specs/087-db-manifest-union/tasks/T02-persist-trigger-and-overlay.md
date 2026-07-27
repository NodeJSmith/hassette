---
task_id: "T02"
title: "Add manifest persist triggers and overlay function"
status: "planned"
depends_on: ["T01", "T04"]
implements: ["FR#1", "FR#5", "FR#6", "FR#10", "AC#1", "AC#4", "AC#5", "AC#9", "AC#10", "AC#12"]
---

## Summary

Wire the manifest upsert into the app lifecycle (bootstrap and hot-reload paths) and create the single `overlay_runtime_state()` function that all web routes will call. The persist trigger writes manifest metadata to DB on app load/reload. The overlay function merges DB rows with in-memory runtime state (status, instances, `in_current_config`) at query time. This is the core logic that decouples the web layer from the in-memory manifest store.

## Target Files

- modify: `src/hassette/core/app_lifecycle_service.py`
- modify: `src/hassette/core/app_registry.py`
- read: `src/hassette/core/app_handler.py` (lifecycle hooks, depends_on)
- read: `src/hassette/core/database_service.py` (submit() API)
- modify: `src/hassette/core/command_executor.py` (add manifest upsert wrapper method)
- read: `src/hassette/core/telemetry/repository.py` (upsert method from T01)
- read: `src/hassette/schemas/app_snapshots.py` (AppManifestInfo fields)
- create: `tests/unit/core/test_overlay_runtime_state.py`

## Prompt

### Persist trigger in `app_lifecycle_service.py`

Add a manifest upsert step in two locations per the design doc's `## Architecture → Persist trigger`:

1. **`bootstrap_apps()`** — after `set_apps_configs()` populates the in-memory registry and before `start_apps()`. First, add a new wrapper method on `CommandExecutor` (e.g., `upsert_app_manifest(manifest)`) that internally calls `await self.hassette.database_service.submit(self.repository.upsert_app_manifest(manifest))` — matching the existing `register_listener()`/`register_job()` convention at `command_executor.py:665-707`. Then in `bootstrap_apps()`, iterate `self.registry._manifests` and call `self.hassette.command_executor.upsert_app_manifest(manifest)` for each. Each call is isolated: wrap in try/except with an explicit timeout (e.g., `asyncio.wait_for(..., timeout=5.0)`). On failure, log a warning and continue — never block app startup. Match the fault-isolation style of `start_apps()` (which uses `asyncio.gather(return_exceptions=True)`).

2. **`refresh_config()`** — immediately after `set_apps_configs()` updates the in-memory registry and before `apply_changes()` begins stopping/restarting instances. Same per-item isolation pattern.

### Overlay function in `app_registry.py`

Create a module-level function `overlay_runtime_state(db_rows: list[dict], registry: AppRegistry) -> list[AppManifestInfo]` co-located with `build_manifest_info()`. This function:

- For each `db_row` dict (from the query), checks if `db_row["app_key"]` is in `registry._manifests`
- If found: derives status using the same priority logic as `build_manifest_info()` (disabled > blocked > running > failed > stopped), attaches instance data, sets `in_current_config = True`
- If not found (DB-only app): `status = "stopped"`, `instance_count = 0`, `instances = []`, `in_current_config = False`
- Static metadata (class_name, display_name, etc.) always comes from the DB row
- Returns a list of `AppManifestInfo` (or a new dataclass if AppManifestInfo needs the `in_current_config` field added — check whether AppManifestInfo in `schemas/app_snapshots.py` needs modification)

### Unit tests

Test the overlay function:
- DB row with matching registry entry → correct status derivation, `in_current_config = True`
- DB row with no registry entry → `status = "stopped"`, `in_current_config = False`
- Multiple DB rows, mix of in-config and DB-only → correct list returned
- Status priority: disabled > blocked > running > failed > stopped (each variant)

## Focus

- `bootstrap_apps()` is at `app_lifecycle_service.py:296-326`. Its outer `try/except Exception: handle_crash(self, exc); raise` wrapper must NOT catch manifest upsert failures — the per-item try/except must catch them first. The upsert step goes inside the try block, before `start_apps()`.
- `refresh_config()` is at `app_lifecycle_service.py:494-509`. The upsert goes after `set_apps_configs()` and before `apply_changes()`.
- `build_manifest_info()` at `app_registry.py:201-245` is the reference for status derivation. The overlay function reuses its logic but takes a DB row dict instead of an `AppManifest`.
- `AppManifestInfo` in `schemas/app_snapshots.py:62-80` may need an `in_current_config: bool = True` field added. Check if it already has one.
- The `only_apps` field on `AppFullSnapshot` stays sourced from `registry._only_apps` — it's not in the overlay function.
- Access to the repository: the established convention (used elsewhere in `app_lifecycle_service.py:660`) is `self.hassette.command_executor.<method>()` — `TelemetryRepository` lives on `CommandExecutor`, not directly on `DatabaseService`. Follow the existing `register_listener`/`register_job` call pattern.

## Verify

- [ ] FR#1: After hassette boots, manifest metadata is persisted to the DB — verifiable by checking `SELECT * FROM app_manifests` has rows matching the configured apps.
- [ ] FR#5: The overlay function produces correct runtime status for apps with in-memory state.
- [ ] FR#6: The overlay function defaults to "stopped" with zero instances for DB-only apps.
- [ ] FR#10: The overlay function returns DB-only apps (removed from config) alongside in-config apps.
- [ ] AC#1: `GET /apps/manifests` returns entries with correct metadata fields after boot (depends on T03 wiring, but the persist trigger and overlay are prerequisites).
- [ ] AC#4: Running apps show correct runtime status via the overlay (verified via unit test).
- [ ] AC#5: DB-only apps show `status: "stopped"`, `instance_count: 0` (verified via unit test).
- [ ] AC#9: Removed apps appear in the overlay output with historical data (verified via unit test).
- [ ] AC#10: After hot-reload, updated metadata is persisted (verifiable by calling the upsert in test and querying).
- [ ] AC#12: `in_current_config` is `true` for configured apps, `false` for DB-only apps (verified via unit test).
