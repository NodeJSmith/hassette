---
task_id: "T06"
title: "Update API, CLI, and web enrichment for schedule status"
status: "planned"
depends_on: ["T04", "T05"]
implements: ["FR#14", "FR#15", "FR#16", "FR#22", "AC#7", "AC#11", "AC#12"]
---

## Summary

Update the web API routes, response models, CLI job command, and live enrichment to expose `schedule_status`, `schedule_status_reason`, and nullable `next_run`. Implement the shared submission endpoint (202 accepted for live, 409 for non-live). Update the CLI to render truthful status text instead of generic "done" for null times. Update enrichment to join from the registry instead of the heap.

## Target Files

- modify: `src/hassette/web/routes/scheduler.py`
- modify: `src/hassette/web/routes/telemetry.py`
- modify: `src/hassette/web/utils.py`
- modify: `src/hassette/web/models.py`
- modify: `src/hassette/schemas/job_models.py`
- modify: `src/hassette/cli/commands/job.py`
- modify: `src/hassette/test_utils/web_mocks.py`
- read: `design/specs/090-registered-manual-jobs/design.md` (Architecture > Operator Surfaces, Manual Submission)
- modify: `tests/integration/web_api/test_trigger_job.py`
- modify: `tests/integration/telemetry/test_global_jobs_and_service_info.py`
- modify: `tests/unit/core/test_scheduler_service_trigger.py`

## Prompt

**Update response models:**

- `JobSummary` in `src/hassette/schemas/job_models.py`: add `schedule_status: str` and `schedule_status_reason: str | None` fields. Update the `none_text` annotation on `next_run` — it no longer always means "done".
- Web response model in `src/hassette/web/models.py`: add schedule status fields to the job response.

**Update enrichment** in `src/hassette/web/utils.py`:

- Rename both the sync helper `enrich_jobs_with_heap()` → `enrich_jobs_with_live()` and the async wrapper `enrich_jobs_with_live_heap()` → `enrich_jobs_with_live_data()` (or similar — the "heap" in both names is now misleading since enrichment reads from the registry). Join all live jobs from `_jobs_by_id` (the registry), not just the heap.
- Include `schedule_status`, `schedule_status_reason`, nullable `next_run`, `fire_at`, and `jitter` in the enrichment overlay.
- Scheduled jobs get timing from live state; waiting/completed/manual jobs get null timing.
- On enrichment failure, persisted status and reason remain available but timing is null.

**Update submission route** in `src/hassette/web/routes/scheduler.py`:

- Remove the one-shot dequeue logic and `single` preflight conflict check.
- Resolve the job by `db_id` from the registry (`_jobs_by_id`), not the heap.
- Call `scheduler_service.submit_job(job)`.
- A live registration always returns 202 accepted.
- A missing live registration (persisted but not live) returns 409.

**Update `web/routes/telemetry.py`:**
- The `app_jobs` route calls `enrich_jobs_with_live_heap()` — update to the renamed enrichment function.

**Update CLI** in `src/hassette/cli/commands/job.py`:

- Add a schedule status column.
- Render null `next_run` with status-aware text:
  - `scheduled` with null timing: "Timing unavailable"
  - `scheduled` with `legacy_unknown`: "Legacy status unknown"
  - `waiting`: "Waiting for entity time"
  - `completed` without reason: "Schedule completed"
  - `completed` with `trigger_error`: "Schedule stopped after trigger error."
  - `manual`: "Manual only"

**Update test mocks:**
- `src/hassette/test_utils/web_mocks.py`: update `get_all_jobs` mock for registry-based lookup.

**Regenerate schemas and types** after all changes:
```bash
uv run python scripts/export_schemas.py --types
```

See design doc: Architecture > Operator Surfaces, Manual Submission.

## Focus

- `web/routes/scheduler.py` currently has `trigger_job()` at line ~60 with two 409 paths (already running, already fired). Both are removed — submission always returns 202 for live jobs.
- `web/routes/telemetry.py` also calls `enrich_jobs_with_live_heap` — must be updated alongside the scheduler route.
- `web/utils.py`'s enrichment currently assumes every live job has concrete `next_run` — this assumption must be relaxed for waiting/completed/manual jobs.
- `JobSummary.next_run` uses `Annotated[float | None, ...]` with `none_text="done"` — this annotation needs updating since null no longer always means done.
- The `web/CLAUDE.md` `SchedulerDep` description update is covered in T08 (docs/tooling).

## Verify

- [ ] FR#14: API and CLI submission use the same `submit_job()` service path as `Job.submit()`.
- [ ] FR#15: Remote submission of a live job returns 202 even when overlap policy later suppresses.
- [ ] FR#16: Remote submission of a persisted but non-live job returns 409. Submitting through a removed handle raises `JobRemovedError`.
- [ ] FR#22: Job summaries expose `schedule_status` and nullable `next_run`. CLI and API distinguish waiting, completed, and manual states.
- [ ] AC#7: API and CLI tests demonstrate all four schedule statuses, nullable next-run rendering, accepted submissions, and 409 for non-live jobs.
- [ ] AC#11: API tests demonstrate that trigger_error completion is exposed in normal and degraded job summaries with the correct reason.
- [ ] AC#12: Migration/API tests demonstrate legacy rows use `legacy_unknown`, removed legacy rows are excluded, and live re-registration clears the placeholder.
