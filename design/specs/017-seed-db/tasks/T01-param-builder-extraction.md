---
task_id: "T01"
title: "Extract and publicize param builder functions"
status: "done"
depends_on: []
implements: ["FR#3", "FR#4"]
---

## Summary

Make the param builder functions importable by dropping their underscore prefix, and extract `job_insert_params` from the inline dict in `register_job()`. This is the foundation for the seed script's write path — all subsequent tasks depend on these functions being importable. Also update the existing test file that imports the underscore-prefixed name.

## Target Files

- modify: `src/hassette/core/telemetry/repository.py`
- modify: `tests/integration/telemetry/test_telemetry_execution_id.py`
- modify: `tests/integration/test_thread_leaked_observability.py`
- read: `src/hassette/core/execution_record.py`
- read: `src/hassette/core/registration.py`

## Prompt

In `src/hassette/core/telemetry/repository.py`:

1. **Rename `_execution_insert_params` → `execution_insert_params`**. This is a module-level function (line 28). Update all internal callers in the same file: the `_EXECUTION_INSERT_SQL` derivation (line 70), `persist_execution_batch` (line 623), and `persist_execution_batch_with_fk_fallback` (line 653).

2. **Rename `_listener_insert_params` → `listener_insert_params`**. Module-level function (line 90). Update the internal caller in `register_listener` (line 325).

3. **Extract `job_insert_params` as a new module-level function**. Currently the INSERT parameter dict is built inline inside `register_job()` (around lines 391-409). Extract it to a standalone function `job_insert_params(registration: ScheduledJobRegistration) -> dict[str, Any]` following the same pattern as the other two builders. **Critical**: hardcode `"repeat": 0` in the extracted function — this is an invariant (`repeat` is always 0 for new-style jobs, and `ScheduledJobRegistration` has no `repeat` field). Call the new function from `register_job()`.

In `tests/integration/telemetry/test_telemetry_execution_id.py`:

4. **Update the import** on line 13: change `_execution_insert_params` to `execution_insert_params`. Update the two call sites at lines 149 and 208. Also update the docstring references at lines 135 and 196 that mention `_execution_insert_params()` in prose.

In `tests/integration/test_thread_leaked_observability.py`:

5. **Update docstring/comment references** at lines 306 and 317: change `_execution_insert_params` to `execution_insert_params`.

## Focus

- The `register_job()` method's inline dict includes fields from `registration` plus the hardcoded `"repeat": 0`. Read the full method to capture every field — don't miss any.
- `_EXECUTION_INSERT_SQL` is derived from calling `_execution_insert_params` with a dummy record to get the column names (lines 70-78). This derivation must continue to work after the rename.
- The `__all__` export list in `repository.py` (if one exists) may need updating. Check.
- Run `prek -a` after changes to verify lint + type check pass.

## Verify

- [ ] FR#3: `execution_insert_params`, `listener_insert_params`, and `job_insert_params` are importable from `hassette.core.telemetry.repository` (no underscore prefix)
- [ ] FR#4: `job_insert_params(make_job_registration())` produces a dict with `"repeat": 0` and all fields matching the inline dict in the original `register_job()` method
