---
task_id: "T09"
title: "Unify command executor record building and persist logic"
status: "planned"
depends_on: ["T05", "T06", "T07", "T08"]
implements: ["FR#1", "AC#1"]
---

## Summary
Merge the dual-branch record building (`_build_record`) and dual-list persist logic (`_persist_batch`, `_drain_and_persist`, `RetryableBatch`) in `command_executor.py` into single-path equivalents that produce unified `ExecutionRecord` objects. Collapse event emission from two topics to one.

## Prompt
**Step 1: Merge `_build_record()`** — the current `match cmd:` has two cases (`InvokeHandler`, `ExecuteJob`) producing `HandlerInvocationRecord` and `JobExecutionRecord`. Both merge into a single path producing `ExecutionRecord` with the appropriate `kind`.

**Step 2: Simplify `RetryableBatch`** — replace `invocations: list[HandlerInvocationRecord]` + `job_executions: list[JobExecutionRecord]` with a single `records: list[ExecutionRecord]`.

**Step 3: Merge `_persist_batch()`** — the dual-list session ID injection and `repository.persist_batch()` call collapse to single-list equivalents. Sentinel filtering (db_id=0 records) was eliminated in T04 — confirm it's gone.

**Step 4: Merge `_drain_and_persist()`** — merge dual drain logic.

**Step 5: Collapse event emission** — update `_emit_completion_events()` to emit a single event type on one topic instead of two separate topics (`HASSETTE_EVENT_INVOCATION_COMPLETED` and `HASSETTE_EVENT_EXECUTION_COMPLETED`). Define or rename the unified topic constant (e.g., `Topic.HASSETTE_EVENT_EXECUTION_COMPLETED`). The payload already includes `owner_key` and `instance_index` (from T06) and `kind` to distinguish handler vs job.

**Step 6: Update tests** — `test_command_executor.py` (both unit and integration) has dual-list persist tests. Update for unified records. Remove sentinel=0 filtering tests (eliminated in T04).

## Focus
- `source_tier` filtering logic should be unchanged — framework executions are still filtered from user-facing views.
- The old `HASSETTE_EVENT_INVOCATION_COMPLETED` topic constant should be removed to avoid dead subscriptions. Update the Topic enum/constants.
- T11 will update RuntimeQueryService to subscribe to the single unified topic — coordinate.

## Verify
- [ ] FR#1: `_build_record()` produces unified `ExecutionRecord` for both handler and job commands
- [ ] AC#1: Command executor tests pass with unified record types
