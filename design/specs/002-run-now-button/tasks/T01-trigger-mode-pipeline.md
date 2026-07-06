---
task_id: "T01"
title: "Add trigger_mode field to execution pipeline"
status: "done"
depends_on: []
implements: ["FR#6", "AC#5"]
---

## Summary
Add a `trigger_mode` field to the `ExecuteJob` command dataclass and thread it through the execution pipeline so manual triggers can be recorded distinctly from scheduled fires. The field flows from `SchedulerService.run_job_with_guard()` → `run_job()` → `ExecuteJob` → `CommandExecutor.build_record()` → `ExecutionRecord`. All parameters default to `None` so existing call sites are unaffected.

## Target Files
- modify: `src/hassette/commands.py`
- modify: `src/hassette/core/scheduler_service.py`
- modify: `src/hassette/core/command_executor.py`
- read: `src/hassette/schemas/telemetry_models.py`
- create: `tests/unit/core/test_scheduler_service_trigger.py`
- modify: `tests/unit/core/test_command_executor.py`

## Prompt
Add `trigger_mode: str | None = None` to the `ExecuteJob` frozen dataclass in `src/hassette/commands.py` (line 67). This is a new field on the existing dataclass — place it after the existing fields.

In `src/hassette/core/scheduler_service.py`:
- Add an optional `trigger_mode: str | None = None` parameter to `run_job_with_guard()` (line 378). Thread it through to `run_job()` in both code paths: for parallel mode, pass it directly in the `await self.run_job(job, trigger_mode=trigger_mode)` call; for non-parallel modes, capture it in the `invoke` lambda: `invoke=lambda: self.run_job(job, trigger_mode=trigger_mode)`.
- Add an optional `trigger_mode: str | None = None` parameter to `run_job()` (line 420). Pass it to the `ExecuteJob` constructor.

In `src/hassette/core/command_executor.py`, in the `build_record()` method's `ExecuteJob` case (line 471), read `cmd.trigger_mode` and set it on the `ExecutionRecord`. The `ExecutionRecord` dataclass in `src/hassette/schemas/telemetry_models.py` already has a `trigger_mode` field (currently always `None`).

All new parameters must default to `None` so existing call sites (`dispatch_and_log` calling `run_job_with_guard`, `run_job_with_guard` calling `run_job`) continue to work without changes.

Follow the design doc section `## Architecture → trigger_mode threading` for the full specification.

## Focus
- `ExecuteJob` is a frozen dataclass (line 67 of `commands.py`). Adding a field with a default is safe — existing construction sites don't need updating.
- `run_job_with_guard` (line 378) handles four execution modes. For `PARALLEL`, it calls `run_job` directly. For `SINGLE`/`RESTART`/`QUEUED`, it passes an `invoke` lambda to `run_through_guard`. The lambda must capture `trigger_mode` in its closure.
- `build_record` for `ExecuteJob` (lines 471-489) currently does NOT set `trigger_context_id` or `trigger_origin` — those are handler-only fields. `trigger_mode` is the only new field to set.
- `ExecutionRecord.trigger_mode` already exists in `telemetry_models.py` — just currently never populated. No schema migration needed.
- Existing tests in `test_scheduler_service_reschedule.py`, `test_scheduler_service_timeout.py`, and `test_scheduler_service_error_handler.py` call `run_job` and `run_job_with_guard` without `trigger_mode` — they must continue to work (default `None`).
- The unit test file `test_command_executor_pipeline.py` has existing patterns for testing `build_record` field propagation (e.g., `test_build_record_reads_source_tier`, `test_build_record_reads_thread_leaked`). Follow these patterns for the new `trigger_mode` test.

## Verify
- [ ] FR#6: `ExecuteJob` constructed with `trigger_mode="manual"` propagates to `ExecutionRecord.trigger_mode` via `build_record()`
- [ ] AC#5: Unit test confirms `trigger_mode='manual'` appears on the `ExecutionRecord` when passed through the full `run_job_with_guard()` → `run_job()` → `ExecuteJob` → `build_record()` chain
