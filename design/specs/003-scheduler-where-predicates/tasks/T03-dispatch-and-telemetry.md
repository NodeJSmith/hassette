---
task_id: "T03"
title: "Add predicate evaluation in dispatch, skipped record path, and registration telemetry"
status: "done"
depends_on: ["T01", "T02", "T04"]
implements: ["FR#4", "FR#5", "FR#6", "FR#7", "FR#8", "FR#11", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Summary
Implement the core dispatch-time predicate evaluation in `SchedulerService.dispatch_and_log()`, the `_record_skipped()` helper that builds and enqueues an `ExecutionRecord` with `status='skipped'`, and the registration telemetry path that persists `predicate_description`/`human_description` to the database. This is the behavioral heart of the feature — it makes predicates actually gate execution and makes skips visible in telemetry. Integration tests for skip/run/exception scenarios.

## Target Files
- modify: `src/hassette/core/scheduler_service.py`
- modify: `src/hassette/core/telemetry/repository.py`
- read: `src/hassette/core/command_executor.py` (reference for `enqueue_record()`, `build_record()` patterns)
- read: `src/hassette/core/execution_record.py` (ExecutionRecord construction)
- read: `src/hassette/core/bus_service.py` (reference for `build_registration()` pattern)
- read: `src/hassette/utils/func_utils.py` (callable_stable_name)
- modify: `tests/integration/test_scheduler.py`
- read: `tests/unit/core/test_scheduler_service_reschedule.py` (verify rescheduling unaffected by predicate)
- modify: `src/hassette/test_utils/web_helpers.py`
- read: `design/specs/003-scheduler-where-predicates/design.md`

## Prompt
Implement predicate evaluation at dispatch time and registration telemetry:

**1. `src/hassette/core/scheduler_service.py` — predicate evaluation in `dispatch_and_log()` (line 296):**
Insert a predicate check between step 1 (compute next occurrence, lines 316-359) and step 2 (run through guard, lines 361-369). See the pseudocode in `## Architecture > Predicate evaluation` in the design doc. Key behaviors:
- If `job.predicate is not None`, evaluate: `job.predicate(job) if job._predicate_wants_job else job.predicate()`.
- Wrap in try/except: on exception, log warning and set `should_run = True` (fail-open).
- If `not should_run`, call `self._record_skipped(job)`, then if `remove_after_fire` remove the job (with try/except around `_remove_job()` matching step 3's pattern), then return.

**2. `src/hassette/core/scheduler_service.py` — `_record_skipped()` helper:**
Build an `ExecutionRecord` with `status='skipped'`, `duration_ms=0.0`, `kind='job'`, `job_id=job.db_id`, and the current session context. Enqueue it via `self._executor.enqueue_record()`. Do NOT go through `_execute()` or `track_execution()`. Reference `build_record()` in `command_executor.py` (line 426) for the field construction pattern, but build the record directly rather than constructing an `ExecuteJob` command.

**3. `src/hassette/core/scheduler_service.py` — registration telemetry in `add_job()` (line 252):**
When constructing `ScheduledJobRegistration`, populate `predicate_description` and `human_description`:
- `predicate_description = repr(job.predicate) if job.predicate else None`
- For `human_description`: if `job.predicate` has a `summarize()` method (via `hasattr`), call it; otherwise use `callable_stable_name(job.predicate)` from `hassette.utils.func_utils`. Set to `None` if `job.predicate is None`.
Import `callable_stable_name` from `hassette.utils.func_utils` (it's already aliased as `callable_name` in predicates.py, but use the canonical import).

**4. `src/hassette/core/telemetry/repository.py` — `register_job()` SQL (lines 332-406):**
Add `predicate_description` and `human_description` to the INSERT INTO `scheduled_jobs` statement and the ON CONFLICT DO UPDATE clause. Follow the pattern used by `register_listener()` (lines 296-311) which already handles these columns for the `listeners` table. The job insert parameters are built inline in `register_job()` — add the new fields to the parameter dict.

**5. `src/hassette/test_utils/web_helpers.py` — `make_real_job()` (line 270):**
Add optional `predicate` parameter (default `None`) so integration tests can construct jobs with predicates easily.

**6. Integration tests in `tests/integration/test_scheduler.py`:**
- **Recurring job skip:** Register a job with `where=lambda: False` and a recurring trigger, trigger it, verify an execution record with `status='skipped'` was created and the job was rescheduled for its next occurrence.
- **One-shot job skip:** Register `run_in` with `where=lambda: False`, trigger, verify `status='skipped'` record and job removal.
- **Predicate exception (fail-open):** Register with `where=lambda: 1/0`, trigger, verify warning logged and job runs normally (status='success' or similar — not 'skipped').
- **Predicate receives ScheduledJob:** Register with `where=lambda job: job.kwargs.get("key") == "expected"`, pass matching kwargs, verify job runs.
- **No predicate (baseline):** Confirm existing behavior is unchanged — a job without `where=` executes unconditionally.

See `## Architecture > Predicate evaluation`, `## Architecture > Predicate summarization`, and `## Architecture > Registration telemetry` in the design doc.

## Focus
- The predicate check MUST come after step 1 (next occurrence computed and enqueued) and BEFORE step 2 (run through guard). If placed before step 1, a skipped recurring job would not compute its next occurrence and would stop firing.
- The `_record_skipped()` path bypasses `_execute()` entirely. It needs to obtain `session_id` from the executor's current session context — check how `build_record()` (command_executor.py:426) gets it.
- Gap found in exploration: `src/hassette/core/telemetry/repository.py::register_job()` INSERT/UPDATE SQL does not include `predicate_description`/`human_description` columns. Without this fix, the registration data would be silently dropped. The sibling `register_listener()` path (lines 296-311) already has the pattern to copy.
- Gap found: `src/hassette/test_utils/web_helpers.py::make_real_job()` needs an optional `predicate` param for integration test convenience.
- The `ExecutionRecord` for skips should have `execution_id` generated the same way as normal executions (UUID4), not `None`.
- `callable_stable_name` returns `"<callable>"` for lambdas/closures — this is expected and documented in the design.
- **Manual trigger bypass (intentional):** The `POST /api/scheduler/jobs/{job_id}/trigger` endpoint (added by #1216) calls `run_job_with_guard()` directly, not `dispatch_and_log()`. The predicate check lives inside `dispatch_and_log()`, so manual triggers bypass it. This is intentional — "Run Now" is an explicit operator action that always fires regardless of `where=`. Do NOT add predicate checks to `run_job_with_guard()` or `trigger_job()`.

## Verify
- [ ] FR#4: A job with `where=lambda: False` does not execute its handler
- [ ] FR#5: A skipped execution produces an `ExecutionRecord` with `status='skipped'` and `duration_ms=0.0`
- [ ] FR#6: A recurring job with a failing predicate is rescheduled for its next occurrence
- [ ] FR#7: A one-shot job with a failing predicate is consumed (removed from the scheduler)
- [ ] FR#8: A predicate that raises an exception logs a warning and the job runs (fail-open)
- [ ] FR#11: `predicate_description` and `human_description` are persisted to the `scheduled_jobs` table via `register_job()`
- [ ] AC#1: Tests confirm a job with `where=lambda: False` produces `'skipped'` records and never invokes the handler
- [ ] AC#2: Tests confirm a recurring job is rescheduled after a skip
- [ ] AC#3: Tests confirm a one-shot job is consumed after a skip
- [ ] AC#4: Tests confirm a predicate exception is logged and the job runs
