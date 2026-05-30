---
task_id: "T07"
title: "Unify execution models and record types"
status: "done"
depends_on: ["T02"]
implements: ["FR#1", "FR#17", "AC#11", "AC#12"]
---

## Summary
Replace `HandlerInvocation` + `JobExecution` models with a unified `Execution` model with `kind` discriminator. Replace `HandlerInvocationRecord` + `JobExecutionRecord` with a unified `ExecutionRecord`. Update `ActivityFeedEntry.row_id` to use `execution_id` UUID.

## Prompt
**Step 1: Update `core/telemetry_models.py`:**
- Delete `HandlerInvocation` and `JobExecution` model classes.
- Create unified `Execution` model with `kind: Literal["handler", "job"]`, all shared fields, and optional handler-only fields (`trigger_context_id`, `trigger_origin`). Include new columns: `trigger_mode`, `retry_count`, `attempt_number`, `args_json`, `kwargs_json`.
- `ActivityFeedEntry.row_id` now uses `execution_id` (UUID string) instead of `'h-' || rowid` / `'j-' || rowid`.
- Keep `AppHealthSummary` split fields unchanged (`total_invocations`/`total_executions`, etc.).

**Step 2: Update `bus/invocation_record.py`** (if separate from `invocation.py`):
- Replace `HandlerInvocationRecord` with a unified `ExecutionRecord` that includes `kind` field.

**Step 3: Update `scheduler/classes.py`:**
- Replace `JobExecutionRecord` with the same unified `ExecutionRecord` or import from the shared location.

**Step 4: Write unit tests:**
- Test: unified Execution model accepts both handler and job kinds
- Test: kind field rejects invalid values via Pydantic validation
- Test: new columns exist on the model with correct defaults
- Test: handler-only fields are None when kind="job"

## Focus
- `HandlerInvocationRecord` lives in `bus/invocation_record.py` — verify the exact path.
- `JobExecutionRecord` lives in `scheduler/classes.py`.
- Both record types are consumed by `CommandExecutor._build_record()` and `_persist_batch()` — those are updated in T09.
- `test_telemetry_models.py` and `test_model_types.py` have existing tests — update or replace.
- `e2e/mock_fixtures.py` builds test data using old model types — update.

## Verify
- [ ] FR#1: A single `Execution` model exists with `kind` discriminator
- [ ] FR#17: `kind` field accepts only `"handler"` and `"job"` (Pydantic validation)
- [ ] AC#11: Unit test confirms invalid kind values are rejected
- [ ] AC#12: New columns (`trigger_mode`, `retry_count`, `attempt_number`, `args_json`, `kwargs_json`) exist on the model with correct defaults
