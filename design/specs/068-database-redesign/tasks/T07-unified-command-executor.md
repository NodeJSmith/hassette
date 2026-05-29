---
task_id: "T07"
title: "Unify command executor record building and persist logic"
status: "planned"
depends_on: ["T04", "T05", "T06"]
implements: ["FR#1", "AC#1"]
---

## Summary
Merge the dual-branch record building (`_build_record`) and dual-list persist logic (`_persist_batch`, `_drain_and_persist`, `RetryableBatch`) in `command_executor.py` into single-path equivalents that produce unified `ExecutionRecord` objects.

## Prompt
**Step 1: Merge `_build_record()`** — the current `match cmd:` has two cases (`InvokeHandler`, `ExecuteJob`) producing `HandlerInvocationRecord` and `JobExecutionRecord`. Both merge into a single path producing `ExecutionRecord` with the appropriate `kind`.

**Step 2: Simplify `RetryableBatch`** — replace `invocations: list[HandlerInvocationRecord]` + `job_executions: list[JobExecutionRecord]` with a single `records: list[ExecutionRecord]`.

**Step 3: Merge `_persist_batch()`** — the dual-list session ID injection, sentinel filtering, and `repository.persist_batch()` call collapse to single-list equivalents.

**Step 4: Merge `_drain_and_persist()`** — merge dual drain logic.

**Step 5: Update `_emit_completion_events()`** — emit a single `execution_completed` event type instead of separate `invocation_completed` and `execution_completed`. The payload now includes `owner_key` and `instance_index` (from T04).

**Step 6: Update tests** — `test_command_executor.py` (both unit and integration) has dual-list persist tests, sentinel filtering tests. Update for unified records. Remove sentinel=0 filtering tests (sentinel architecture eliminated in T04).

## Focus
- Sentinel filtering (db_id=0 records) was eliminated in T04 — confirm it's gone from `_persist_batch()`.
- The `_emit_completion_events()` method currently emits to two different topics (`INVOCATION_COMPLETED`, `EXECUTION_COMPLETED`). Under the new design, only one topic is needed. Coordinate with the event topic definitions.
- `source_tier` filtering logic should be unchanged — framework executions are still filtered from user-facing views.

## Verify
- [ ] FR#1: `_build_record()` produces unified `ExecutionRecord` for both handler and job commands
- [ ] AC#1: Command executor tests pass with unified record types
