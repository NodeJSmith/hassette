---
task_id: "T03"
title: "Add instance-scoped DB reconciliation"
status: "done"
depends_on: []
implements: ["FR#4", "AC#4"]
---

## Summary
Extend the telemetry reconciliation queries to support optional `instance_index` scoping. Currently, `_build_delete_query()`, `_build_retire_query()`, and the hand-written `once=True` cleanup block all scope by `app_key` only. After this change, passing `instance_index` restricts all five SQL paths to that specific instance, so restarting one instance does not retire sibling instances' listener/job rows.

## Target Files
- modify: `src/hassette/core/telemetry/repository.py`
- modify: `src/hassette/core/command_executor.py`
- modify: `src/hassette/core/app_lifecycle_service.py` (initialize_instances, reconcile_app_registrations signatures)
- modify: `tests/unit/core/test_telemetry_repository.py`
- modify: `tests/unit/core/conftest.py` (if fixtures need updating)
- read: `design/specs/104-per-instance-restart/design.md`

## Prompt
Extend instance-scoped reconciliation across three layers:

### 1. Telemetry repository (`src/hassette/core/telemetry/repository.py`)

Add a shared helper function to single-source the `instance_index` clause construction:
```python
def _instance_index_clause(instance_index: int | None) -> tuple[str, dict]:
    if instance_index is None:
        return "", {}
    return " AND instance_index = :instance_index", {"instance_index": instance_index}
```

Then extend all five SQL paths in `reconcile_registrations()`:

a. `_build_delete_query()` — add `instance_index: int | None = None` parameter. Use the helper to append the clause and merge params.

b. `_build_retire_query()` — same pattern as (a).

c. The hand-written `once=True` listener cleanup SQL block (lines 625-654) — this block bypasses the builder functions. Add `AND instance_index = :instance_index` when `instance_index` is provided. Use the same helper.

d. The scheduled_jobs `_build_delete_query` call — pass `instance_index` through.

e. The scheduled_jobs `_build_retire_query` call — pass `instance_index` through.

`TelemetryRepository.reconcile_registrations()` gains `instance_index: int | None = None` and passes it to all five SQL paths.

### 2. Command executor (`src/hassette/core/command_executor.py`)

`CommandExecutor.reconcile_registrations()` gains `instance_index: int | None = None` and passes it through to `self.repository.reconcile_registrations()`.

### 3. Lifecycle service (`src/hassette/core/app_lifecycle_service.py`)

Thread `instance_index` through:
- `initialize_instances()` — add `instance_index: int | None = None` parameter, pass to `reconcile_app_registrations()`
- `reconcile_app_registrations()` — add `instance_index: int | None = None` parameter, pass to `command_executor.reconcile_registrations()`

### 4. Tests (`tests/unit/core/test_telemetry_repository.py`)

Add tests verifying:
- `_build_delete_query` with `instance_index` includes `AND instance_index = :instance_index` in the SQL
- `_build_retire_query` with `instance_index` includes the same clause
- The `once=True` cleanup block respects `instance_index`
- All three paths work correctly with `instance_index=None` (backward-compatible, no clause added)

See design doc `## Architecture → Component changes → Telemetry reconciliation` for full details.

## Focus
- The `once=True` block (lines 625-654) is hand-written SQL that bypasses `_build_delete_query`/`_build_retire_query`. Extending only the builders would silently leave this path scoped by `app_key` alone — the exact failure FR#4 exists to prevent.
- All five SQL statements execute inside one `BEGIN`/`COMMIT` transaction (line 604). A missed `instance_index` binding at any of the five sites produces a clean, committed, silent deletion of sibling rows.
- The helper function should be module-level (not a method) to match the existing `_build_delete_query`/`_build_retire_query` pattern.
- `reconcile_registrations` called without `instance_index` (or with `None`) must behave identically to current behavior — backward-compatible optional parameter.
- The `_assert_reconcile_identifiers` allowlist may need updating if `instance_index` is added to the interpolated identifiers.

## Verify
- [ ] FR#4: Unit tests confirm all five SQL paths include `AND instance_index = :instance_index` when the parameter is provided
- [ ] AC#4: Same verification — `_build_delete_query`, `_build_retire_query`, and `once=True` cleanup SQL each include the instance_index clause
