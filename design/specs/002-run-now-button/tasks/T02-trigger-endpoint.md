---
task_id: "T02"
title: "Add POST trigger endpoint and response model"
status: "done"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#7", "AC#1", "AC#2", "AC#3", "AC#4", "AC#6"]
---

## Summary
Add the backend infrastructure for manually triggering a scheduled job: a `trigger_now(db_id)` method on `SchedulerService`, a `JobTriggerResponse` model, and a `POST /api/scheduler/jobs/{job_id}/trigger` endpoint. The endpoint looks up the job on the live heap, pre-checks the guard for single-mode jobs, dequeues one-shot jobs before dispatch, and spawns execution with `trigger_mode="manual"`. Regenerate OpenAPI schema and TypeScript types after adding the response model.

## Target Files
- modify: `src/hassette/core/scheduler_service.py`
- modify: `src/hassette/web/models.py`
- modify: `src/hassette/web/routes/scheduler.py`
- read: `src/hassette/web/routes/apps.py`
- read: `src/hassette/web/dependencies.py`
- read: `src/hassette/web/utils.py`
- read: `src/hassette/execution_mode.py`
- read: `src/hassette/scheduler/triggers.py`
- read: `src/hassette/scheduler/classes.py`
- modify: `tests/unit/core/test_scheduler_service_trigger.py`
- create: `tests/integration/web_api/test_trigger_job.py`
- read: `tests/integration/web_api/conftest.py`
- regenerate: `openapi.json`
- regenerate: `frontend/src/api/generated-types.ts`

## Prompt
### SchedulerService.trigger_now()

Add a new async method `async def trigger_now(db_id: int) -> ScheduledJob` to `SchedulerService` in `src/hassette/core/scheduler_service.py`:

1. Call `get_all_jobs()` to snapshot the heap (line 498).
2. Build a `{db_id: ScheduledJob}` lookup dict (same pattern as the `live_by_db_id` dict comprehension in `src/hassette/web/utils.py:29`).
3. Find the job with matching `db_id`. If not found, raise `ValueError("Job is not currently triggerable")`.
4. Return the `ScheduledJob`.

The method only looks up and returns the job. The route handler performs the guard pre-check and dispatches.

### JobTriggerResponse

Add to `src/hassette/web/models.py`:

```python
class JobTriggerResponse(BaseModel):
    status: str
    job_id: int
    job_name: str
```

This is separate from `ActionResponse` (which has `app_key`/`action` but no `job_id`).

### POST route

Add `POST /api/scheduler/jobs/{job_id}/trigger` to `src/hassette/web/routes/scheduler.py` (which already has the GET `/scheduler/jobs` endpoint at line 16). The handler:

1. Call `scheduler_service.trigger_now(job_id)` — catch `ValueError` → `HTTPException(status_code=409)`.
2. For `SINGLE`-mode jobs only (`job.mode == ExecutionMode.SINGLE`), check `job.guard.is_running()`. If held → `HTTPException(status_code=409, detail="Job is currently executing")`. `RESTART`/`QUEUED`/`PARALLEL` modes skip this pre-check.
3. If the job is a one-shot (`job.trigger is None` or `job.trigger.next_run_time(job.next_run, date_utils.now()) is None`), call `scheduler_service.dequeue_job(job)` to remove it from the heap. This MUST happen BEFORE dispatch — `dequeue_job()` calls `guard.release()` which cancels `current_task`; dequeuing first means the guard has nothing to cancel.
4. Spawn `scheduler_service.run_job_with_guard(job, trigger_mode="manual")` via `task_bucket`. Note: `task_bucket.spawn()` calls `asyncio.create_task()` without executing the coroutine body, so no exceptions from `run_job_with_guard` can propagate to the route handler — there is no RuntimeError catch here (unlike the app-action pattern which awaits the call directly).
5. Return `JobTriggerResponse(status="accepted", job_id=job_id, job_name=job.name)` with `status_code=202`.

Use `SchedulerDep` (already in `src/hassette/web/dependencies.py:45`) for dependency injection. Import `ExecutionMode` from `src/hassette/types/enums.py`. For `date_utils.now()`, use `import hassette.utils.date_utils as date_utils` (matching the existing import in `scheduler_service.py:12`).

Follow the app-action endpoint pattern in `src/hassette/web/routes/apps.py` (lines 104-139) for error handling structure. See the design doc `## Convention Examples → App action endpoint pattern`.

### Schema regeneration

After adding `JobTriggerResponse`, run:
```bash
uv run python scripts/export_schemas.py --types
```

This regenerates `openapi.json`, `ws-schema.json`, `generated-types.ts`, and `ws-types.ts`.

### Integration tests

Add unit tests for `trigger_now()` to `tests/unit/core/test_scheduler_service_trigger.py` (created by T01): test that a job found on the heap is returned, and that a missing `db_id` raises `ValueError`.

Create `tests/integration/web_api/test_trigger_job.py`. Use the existing `mock_hassette` fixture from `tests/integration/web_api/conftest.py` (which provides a `create_hassette_stub`-based mock). Test scenarios:

- POST returns 202 for an active recurring job on the heap
- POST returns 409 when `job_id` is not found on the heap
- POST returns 409 for a single-mode job with guard held (`is_running()` returns `True`)
- POST returns 202 for a restart-mode job with guard held (guard handles overlap)
- POST returns 202 for a queued-mode job with guard held
- POST returns 202 for a parallel-mode job regardless of guard state
- POST with still-pending one-shot job returns 202 and calls `dequeue_job`
- Verify `trigger_mode="manual"` is passed to `run_job_with_guard`
- WebSocket `execution_completed` fires for manual trigger (covered by existing WS infrastructure — note this, no new test needed)

Follow the test patterns in `tests/integration/web_api/test_endpoints.py` for HTTP client usage and assertion style.

## Focus
- The scheduler router uses `prefix="/scheduler"` (line 13 of `routes/scheduler.py`) and is mounted at `/api` (line 70 of `web/app.py`). The full endpoint path is `/api/scheduler/jobs/{job_id}/trigger`.
- `SchedulerDep` is `Annotated["SchedulerService", Depends(get_scheduler)]` — no new dependency wiring needed.
- `dequeue_job` (line 511 of `scheduler_service.py`) is synchronous: it sets `_dequeued=True`, spawns a guard release task, and fires removal callbacks. It does NOT await anything. The guard release task runs on the next event loop tick.
- For one-shot detection: `After.next_run_time()` always returns `None` (line 32 of `triggers.py`). `Once.next_run_time()` always returns `None` (line 81). Checking `job.trigger is None` alone would miss these — real one-shot jobs have trigger objects.
- `run_job_with_guard` is currently only called from `dispatch_and_log` (line 363). This endpoint is the second call site.
- The `mock_hassette` fixture in the web_api conftest uses `create_hassette_stub()` which returns a `MagicMock`. You'll need to configure `mock_hassette.scheduler_service.trigger_now` and `mock_hassette.scheduler_service.run_job_with_guard` as appropriate for each test.
- `task_bucket` is available on the scheduler service via `self._task_bucket` — use `self._task_bucket.spawn()` to fire-and-forget the execution.

## Verify
- [ ] FR#1: POST `/api/scheduler/jobs/{job_id}/trigger` with no body returns 202 with `JobTriggerResponse`
- [ ] FR#2: POST with unknown `job_id` returns 409 with descriptive message
- [ ] FR#3: POST with still-pending one-shot job returns 202 and calls `dequeue_job` before dispatch
- [ ] FR#4: POST with single-mode guard held returns 409; restart/queued modes return 202
- [ ] FR#5: Dispatched job executes through `run_job_with_guard()` with `trigger_mode="manual"`
- [ ] FR#7: WebSocket `execution_completed` fires for manual triggers (existing infrastructure, no new test)
- [ ] AC#1: Active recurring job trigger returns 202 and dispatches through `run_job_with_guard`
- [ ] AC#2: One-shot job not on heap returns 409
- [ ] AC#3: Still-pending one-shot executes and is dequeued
- [ ] AC#4: Guard pre-check correct per execution mode
- [ ] AC#6: Execution appears in frontend via WS (existing infrastructure)
