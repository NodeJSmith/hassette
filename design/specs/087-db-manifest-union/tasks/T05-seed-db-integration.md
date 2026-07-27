---
task_id: "T05"
title: "Add app manifest seeding to seed_db.py"
status: "done"
depends_on: ["T01"]
implements: ["FR#8", "AC#7"]
---

## Summary

Extend `SeedContext` with an `add_app_manifest()` method and update all seed scenarios to call it before adding listeners/jobs. Add a parity assertion test ensuring every scenario's manifest app_keys are a superset of its listener/job app_keys — catching forgotten manifest calls that would silently reproduce the bug this design fixes.

## Target Files

- modify: `scripts/seed_db.py`
- read: `src/hassette/core/telemetry/repository.py` (manifest_insert_params from T01)
- create: `tests/unit/test_seed_db.py` (or add to existing seed test file)

## Prompt

### `SeedContext.add_app_manifest()` in `seed_db.py`

Add a synchronous `add_app_manifest()` method to `SeedContext`, following the existing `add_listener()` / `add_job()` pattern. `SeedContext` uses synchronous `sqlite3.Cursor` via `insert_row()` / `_build_insert_sql()` — NOT async aiosqlite.

The method signature:

```python
def add_app_manifest(
    self,
    *,
    app_key: str,
    class_name: str,
    display_name: str,
    filename: str,
    enabled: bool = True,
    autostart: bool = True,
    auto_loaded: bool = False,
) -> int:
```

It builds the insert params dict, calls `_build_insert_sql("app_manifests", params, returning=True)`, and returns the row id via `insert_row()`.

### Update all seed scenarios

Search `seed_db.py` for every scenario function (e.g., `scenario_healthy`, `scenario_empty`, `scenario_degraded`, etc.). In each scenario, before the first `add_listener()` or `add_job()` call for each app, add a corresponding `ctx.add_app_manifest(app_key=..., class_name=..., display_name=..., filename=...)` call using the same `app_key`, `class_name`, and `display_name` values the scenario already defines.

### Parity assertion test

Write a test that runs each seed scenario, then asserts:
```python
manifest_keys = {row["app_key"] for row in cursor.execute("SELECT app_key FROM app_manifests")}
listener_keys = {row["app_key"] for row in cursor.execute("SELECT DISTINCT app_key FROM listeners")}
job_keys = {row["app_key"] for row in cursor.execute("SELECT DISTINCT app_key FROM scheduled_jobs")}
assert manifest_keys >= listener_keys | job_keys, f"Missing manifests for: {(listener_keys | job_keys) - manifest_keys}"
```

This catches the exact regression class that motivated this design — a scenario with listeners/jobs but no manifest entry.

## Focus

- `SeedContext` at `scripts/seed_db.py:177-332` — study the existing `add_listener()` and `add_job()` methods for the exact pattern (they use `insert_row(self.cursor, sql, params)`).
- Each scenario function is named `scenario_<name>` and receives a `SeedContext` — grep for them.
- The scenarios use deterministic data — manifest metadata should also be deterministic and match what the scenario's listeners/jobs use.
- The `_build_insert_sql()` helper generates INSERT SQL from a params dict — it handles column listing automatically.
- Boolean fields must be stored as integers in the params dict (SQLite convention).

## Verify

- [ ] FR#8: `seed_db.py --scenario healthy` produces a DB with `app_manifests` rows for all scenario apps — verifiable by running the script and querying the table.
- [x] AC#7: Dashboard endpoints return all scenario apps with correct metadata when run against the seeded DB. Accepted as satisfied by this task's DB-row-level verification; end-to-end dashboard verification is T02/T03's scope (both complete).
