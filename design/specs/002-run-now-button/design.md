# Design: Run Now Button for Scheduled Jobs

**Date:** 2026-07-06
**Status:** draft
**Scope-mode:** hold
**Research:** design/research/2026-07-06-run-now-button/research.md

## Problem

The web UI displays scheduled jobs with full execution history, stats, and next-run times, but provides no way to manually trigger a job. Every peer scheduler framework (Airflow, n8n, Prefect, Temporal) offers "run now" from the UI. Without it, developers debugging automations must wait for the next scheduled fire time, and home users cannot manually trigger an automation when they need it outside its schedule.

## Goals

- A user can trigger any active scheduled job immediately from the app detail page
- Manual executions are recorded with `trigger_mode="manual"` and visually distinguished from scheduled executions in the UI
- The trigger respects execution-mode guards (single/restart/queued) and provides immediate feedback when the job cannot run
- Already-fired one-shot jobs return a clear error rather than silently failing

## Non-Goals

- Parameter override UI (Layer 2 — schema-driven forms for passing arguments to the triggered job)
- "Run Now" button on the global `/handlers` page (follow-up if users request it)
- Populating `trigger_mode` for non-manual execution types (scheduled, event-triggered) — tracked in #648

## User Scenarios

### App developer: debugging scheduled automations
- **Goal:** test a scheduled job without waiting for the timer
- **Context:** developing or debugging an automation, viewing the app detail page's handlers tab

#### Trigger a recurring job

1. **Navigate to app detail → handlers tab**
   - Sees: list of listeners and jobs for the app, with a job selected showing its detail panel
   - Decides: which job to trigger
   - Then: clicks the "Run Now" button in the job detail panel

2. **Click "Run Now"**
   - Sees: button enters loading state (spinner)
   - Then: endpoint accepts the trigger (202), job executes in the background

3. **Observe result**
   - Sees: new execution row appears in the execution history table (via WebSocket), with a "manual" chip distinguishing it from scheduled runs
   - Decides: whether the job behaved correctly by expanding the execution detail

#### Trigger a single-mode job that is already running

1. **Click "Run Now" on a job that is currently executing**
   - Sees: error message indicating the job is already running
   - Then: no execution is dispatched; the user waits or checks the running execution

#### Trigger an already-fired one-shot job

1. **Click "Run Now" on a `run_in` or `run_once` job that has already completed**
   - Sees: error message indicating the job has already completed and is no longer active
   - Then: no execution is dispatched

### Home user: manually triggering an automation
- **Goal:** fire a scheduled automation outside its normal schedule
- **Context:** wants to trigger a cover-close or light-scene job right now, viewing the dashboard

#### Trigger from the app detail page

1. **Navigate to app → handlers tab → select the job**
   - Sees: job detail with schedule info, execution history, and a "Run Now" button
   - Decides: to trigger the job now
   - Then: clicks "Run Now", sees loading state, then the new execution in the history

## Functional Requirements

- **FR#1** A POST endpoint at `/api/scheduler/jobs/{job_id}/trigger` with no request body returns HTTP 202 with a response body confirming the trigger was accepted
- **FR#2** The endpoint looks up the job by `db_id` on the live scheduler heap; if the job is not found, the endpoint returns HTTP 409 with a message indicating the job is not currently triggerable. This covers three cases: one-shot already fired, one-shot mid-execution from its scheduled fire (popped from heap by `dispatch_and_log()`, never re-enqueued), and app not running. 409 (not 404) because the job exists as a DB resource — it is the job's *state* that prevents the action, not its absence
- **FR#3** When a one-shot job is manually triggered, the route handler dequeues it from the heap before dispatching execution, preventing a second scheduled fire at the original time. A job is one-shot when `job.trigger is None` or `job.trigger.next_run_time(job.next_run, now) is None` — this covers `After` and `Once` triggers (whose `next_run_time()` returns `None`) as well as bare schedulings with no trigger object
- **FR#4** Before dispatching a `SINGLE`-mode job, the endpoint checks the job's execution-mode guard; if the guard is held (job currently running), the endpoint returns HTTP 409 with a message indicating the job is currently executing. `RESTART`-mode and `QUEUED`-mode jobs bypass the pre-check and dispatch through the guard normally (restart cancels and replaces; queued enqueues)
- **FR#5** When dispatched, the job executes through `run_job_with_guard()` → `run_job()`, preserving the same execution path as scheduled fires (timeout enforcement, error handling, execution recording)
- **FR#6** Manual executions are recorded with `trigger_mode="manual"` in the `executions` table
- **FR#7** The existing `execution_completed` WebSocket message fires for manual executions with `kind="job"` and the matching `job_id`, triggering automatic execution table invalidation in the frontend
- **FR#8** A "Run Now" button appears in the job detail panel on the app detail page's handlers tab, with loading state during the request and inline error display on failure
- **FR#9** Execution table rows display a `<Badge variant="info" size="sm">manual</Badge>` for executions where `trigger_mode="manual"`
- **FR#10** The execution detail panel displays the `trigger_mode` value independently of the existing context fields (`trigger_context_id`, `trigger_origin`), rendered as its own line item when present
- **FR#11** The "Run Now" button is disabled while a trigger request is in flight to prevent double-submission

## Edge Cases

- **One-shot job not on heap:** Job exists in DB (`scheduled_jobs` table) but not on the live heap. This happens when the job has already completed *or* is mid-execution from its scheduled fire (`dispatch_and_log()` pops one-shot jobs from the heap before running them and never re-enqueues). Return 409 with "job is not currently triggerable." The FR#4 guard-busy path is unreachable for one-shot jobs — only recurring jobs (re-enqueued before execution) can hit it.
- **One-shot job still pending:** A `run_in` or `run_once` job that hasn't fired yet is still on the heap. Manually triggering it executes the callable immediately, but `dispatch_and_log()` will also fire the job at the original scheduled time — a double execution. The route handler must dequeue one-shot jobs from the heap *before* dispatching the manual execution (call `dequeue_job()` to remove from heap and `_jobs_by_name` dict). A job is one-shot when `job.trigger is None` or `job.trigger.next_run_time(job.next_run, now) is None` — mirroring `dispatch_and_log()`'s own logic for deciding whether to re-enqueue. Note: `run_in()` creates `trigger = After(...)` (not `None`), so checking `job.trigger is None` alone would miss real one-shot jobs. Dequeue-before-dispatch is critical: `dequeue_job()` calls `guard.release()` which cancels `current_task` — if dispatch ran first, the release would cancel the freshly-spawned execution. Dequeuing first means the guard has no task to cancel, and the subsequent dispatch acquires the guard cleanly.
- **Single-mode guard held:** Job is in `SINGLE` mode and currently executing. Pre-check `guard.is_running()` and return 409 with "job is currently executing" before dispatching. `RESTART` and `QUEUED` mode jobs skip this pre-check — their guards handle the overlap correctly (restart cancels-and-replaces; queued enqueues the trigger).
- **App not running:** Job's owning app is stopped/failed — job won't be on the heap. Same 409 path as one-shot.
- **Rapid double-click:** Frontend disables the button during the request. For parallel-mode jobs, two rapid requests could both succeed — each gets its own execution record, which is correct behavior.
- **Guard race condition (single):** Between the `is_running()` pre-check and `run_job_with_guard()` dispatch, a scheduled fire could acquire the guard. The guard itself handles this correctly (SUPPRESSED outcome, no double-execution), but the user would see 202 followed by no visible execution. Acceptable for a single-user system — the pre-check catches the common case.
- **Job with no db_id:** Jobs that haven't been registered yet (pre-Phase 1 startup) have `db_id=None`. The endpoint takes `job_id` as a path parameter (the DB id), so unregistered jobs are simply not addressable. No special handling needed.

## Acceptance Criteria

- **AC#1** (FR#1, FR#5) Triggering an active recurring job via POST returns 202 and the job's callable executes through the same `run_job_with_guard()` → `run_job()` path as a scheduled fire
- **AC#2** (FR#2) Triggering a one-shot job that has already fired returns 409 with a descriptive error message
- **AC#3** (FR#3) Triggering a still-pending one-shot job executes it immediately and removes it from the scheduler heap, preventing a second scheduled fire
- **AC#4** (FR#4) Triggering a single-mode job that is currently executing returns 409 with a descriptive error message; triggering a restart-mode or queued-mode job that is currently executing returns 202 and dispatches through the guard normally
- **AC#5** (FR#6) The `executions` table row for a manually triggered job has `trigger_mode='manual'`
- **AC#6** (FR#7) After a manual trigger completes, the execution appears in the frontend execution table without a page refresh (via WebSocket)
- **AC#7** (FR#8, FR#11) The "Run Now" button shows a loading spinner during the request and is disabled until the request completes
- **AC#8** (FR#8) When the endpoint returns an error (409, 500), the error message is displayed inline below the button
- **AC#9** (FR#9) Execution rows for manual triggers display a "manual" badge distinguishable from scheduled executions
- **AC#10** (FR#10) The expanded execution detail panel shows the `trigger_mode` value when present

## Key Constraints

- For recurring jobs, the manual trigger must not affect the job's scheduled timing — the job continues on its normal schedule after a manual fire. One-shot jobs are dequeued before dispatch (FR#3) and do not fire again
- The trigger must go through `run_job_with_guard()`, not bypass it — overlap semantics must be respected
- `trigger_mode="manual"` is the only value populated by this change; scheduled and event-triggered executions continue to have `trigger_mode=None`. `trigger_mode` stays as `str | None` (not an enum) — the column predates this work and converting to an enum is orthogonal, best done in #648 when all four values (`event/schedule/manual/retry`) are populated
- The POST endpoint request body must be optional (empty or absent) from the start so Layer 2 can add parameter overrides additively

## Dependencies and Assumptions

- The `trigger_mode` column already exists in the `executions` table (migration `001.sql`) — no schema migration needed
- The `execution_completed` WebSocket message already fires for job executions — no new WS message type needed
- `SchedulerDep` (the FastAPI dependency for `SchedulerService`) is already available in `web/dependencies.py`
- The `ExecutionModeGuard.is_running()` method provides a synchronous pre-check for guard state

## Architecture

### Backend

**New method on `SchedulerService`:** `trigger_now(db_id: int) -> ScheduledJob`

1. Call `get_all_jobs()` to snapshot the heap
2. Build a `{db_id: ScheduledJob}` lookup dict (same pattern as `enrich_jobs_with_heap` in `web/utils.py:29`)
3. Find the job with matching `db_id`; raise `ValueError` if not found
4. Return the `ScheduledJob` — the caller (the route handler) performs the guard pre-check and dispatches

The method returns the job rather than dispatching it so the route handler can pre-check the guard and return appropriate HTTP status codes before committing to execution. Dispatch happens via `run_job_with_guard()` spawned through `task_bucket`.

**`trigger_mode` threading:** Add a `trigger_mode: str | None = None` field to `ExecuteJob` (frozen dataclass in `commands.py`). Add an optional `trigger_mode` parameter to both `SchedulerService.run_job_with_guard()` and `SchedulerService.run_job()`. `run_job_with_guard()` threads `trigger_mode` through to `run_job()` — for parallel mode it passes it directly in the `await self.run_job(job, trigger_mode=trigger_mode)` call, and for non-parallel modes it captures it in the `invoke` lambda: `invoke=lambda: self.run_job(job, trigger_mode=trigger_mode)`. `run_job()` passes it through to the `ExecuteJob` constructor. In `CommandExecutor.build_record()`, read `cmd.trigger_mode` and set it on the `ExecutionRecord`. All parameters default to `None` so existing call sites are unaffected.

**New route:** `POST /api/scheduler/jobs/{job_id}/trigger` in the existing `src/hassette/web/routes/scheduler.py` (which already has the GET `/scheduler/jobs` endpoint). The handler:

1. Calls `scheduler_service.trigger_now(job_id)` — catches `ValueError` → 409
2. For `SINGLE`-mode jobs only, checks `job.guard.is_running()` — if held → 409. `RESTART` and `QUEUED` mode jobs skip the pre-check (their guards handle overlap correctly)
3. If the job is a one-shot (`job.trigger is None` or `job.trigger.next_run_time(job.next_run, now) is None`), dequeues it from the heap via `scheduler_service.dequeue_job(job)` to prevent a second scheduled fire. Dequeue must happen *before* dispatch — `dequeue_job()` calls `guard.release()` which cancels `current_task`; if dispatch ran first, the release would cancel the freshly-spawned execution task before it starts
4. Spawns `scheduler_service.run_job_with_guard(job)` via `task_bucket` (with `trigger_mode="manual"` threaded through). Catches `RuntimeError` → 500 (following the app-actions convention)
5. Returns 202 with `JobTriggerResponse`

**New response model:** `JobTriggerResponse` in `web/models.py`:
```python
class JobTriggerResponse(BaseModel):
    status: str  # "accepted"
    job_id: int
    job_name: str
```

This is separate from `ActionResponse` (which has `app_key` and `action` fields) because the trigger response identifies the job, not the app action.

### Frontend

**"Run Now" button in `JobDetail`:** Add a button to the `extras` prop of `HandlerDetailLayout`, composed alongside the existing `nextRunText` content (wrap both in a fragment or container). The button follows the `ActionButtons` pattern:
- `useSignal(false)` for loading state
- `useSignal<string | null>(null)` for error state
- `exec()` wrapper that sets loading, calls the API, catches errors
- Button is disabled while loading
- Error displayed inline below the button

**New API function:** `triggerJob(jobId: number)` in `endpoints.ts` using `apiPost`.

**`trigger_mode` display in execution table:**
- In the execution row (`execution-table.tsx`): render a `<Badge variant="info" size="sm">manual</Badge>` when `trigger_mode === "manual"`, positioned after the status indicators (same area as the thread-leaked badge)
- In the detail panel (`detail-panel.tsx`): add `trigger_mode` as its own line item, rendered independently of the existing `context` block. The existing context block (`trigger_context_id`/`trigger_origin`) is gated on `trigger_context_id` being truthy, which is always `None` for job executions — so `trigger_mode` must not be placed inside that conditional. Pass `trigger_mode` as a separate prop to `DetailPanel` and render it unconditionally when present

**Type generation:** After adding `JobTriggerResponse` to `models.py`, regenerate OpenAPI schema and TypeScript types via `uv run python scripts/export_schemas.py --types`.

### Guard pre-check detail

The pre-check applies only to `SINGLE`-mode jobs. `is_running()` reads `current_task` and calls `.done()` — both are synchronous. The pre-check and the `run_job_with_guard()` spawn happen in the same async context (the route handler), so no interleaving between check and dispatch from the manual trigger's perspective. A scheduled fire could interleave between pre-check and dispatch (acquiring the guard in `serve()`), but `run_job_with_guard()` handles this correctly — the guard's `run_single()` returns `SUPPRESSED` and the user sees 202 with no visible execution. This is the acceptable race documented in Edge Cases.

Mode-specific behavior:
- **PARALLEL:** No pre-check. Always dispatches.
- **SINGLE:** Pre-check `is_running()`. Returns 409 if held. This is the only mode where a manual trigger would be silently suppressed by the guard, making the pre-check valuable.
- **RESTART:** No pre-check. The guard cancels the running invocation and starts the new one — a manual trigger always results in execution.
- **QUEUED:** No pre-check. The guard enqueues the trigger (up to cap). A manual trigger is accepted or dropped (at cap), matching the same behavior as a scheduled fire.

## Implementation Preferences

No specific implementation preferences — follow codebase conventions.

## Replacement Targets

No existing code is being replaced.

## Convention Examples

### App action endpoint pattern

**Source:** `src/hassette/web/routes/apps.py`

```python
@router.post("/apps/{app_key}/start", status_code=202, response_model=ActionResponse)
async def start_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette)
    try:
        await hassette.app_handler.start_app(app_key)
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to start app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="start")
```

### Action button loading pattern

**Source:** `frontend/src/components/shared/action-buttons.tsx`

```tsx
const loading = useSignal(false);
const error = useSignal<string | null>(null);

const exec = async (action: (key: string) => Promise<unknown>) => {
  if (loading.value) return;
  error.value = null;
  loading.value = true;
  try {
    await action(appKey);
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
};
```

### API POST endpoint function

**Source:** `frontend/src/api/endpoints.ts`

```typescript
export const startApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${encodeURIComponent(appKey)}/start`);
```

### Job lookup by db_id from live heap

**Source:** `src/hassette/web/utils.py`

```python
live_by_db_id = {job.db_id: job for job in live_jobs if job.db_id is not None}
```

### Execution record building for jobs

**Source:** `src/hassette/core/command_executor.py`

```python
case ExecuteJob():
    return ExecutionRecord(
        kind="job",
        listener_id=None,
        job_id=cmd.job_db_id,
        session_id=session_id,
        execution_start_ts=execution_start_ts,
        duration_ms=result.duration_ms,
        status=result.status,
        app_key=cmd.job.app_key,
        instance_index=cmd.job.instance_index,
        source_tier=cmd.source_tier,
        # ... error fields ...
        execution_id=execution_id,
    )
```

## Alternatives Considered

### Synchronous execution with inline result (rejected)

The endpoint awaits job completion and returns the result in the HTTP response. Pros: immediate success/failure feedback without WebSocket. Cons: blocks the HTTP connection for the full job duration (could be 30s+ with timeout), ties up a FastAPI worker, introduces a new response pattern inconsistent with the existing fire-and-forget app actions, and requires modifying `run_job_with_guard` to return an outcome enum. The existing WebSocket infrastructure provides equivalent feedback without blocking.

### Silent 202 without guard pre-check (deferred)

Accept all triggers with 202 and let the guard handle suppression silently. Simpler implementation but poor UX — the user clicks "Run Now" and nothing visible happens when the job is suppressed. The pre-check adds minimal complexity (one `is_running()` call) and provides clear feedback for the most common failure case.

## Test Strategy

### Existing Tests to Adapt

- `tests/integration/web_api/test_endpoints.py` — contains app action endpoint tests (start/stop/reload). No adaptation needed, but the new trigger endpoint tests follow the same patterns.

### New Test Coverage

**Unit tests:**
- `SchedulerService.trigger_now()` — job found on heap returns it; job not found raises `ValueError` (FR#2)
- `ExecuteJob` with `trigger_mode` field — frozen dataclass construction (FR#6)
- `CommandExecutor.build_record()` — `trigger_mode` propagated from `ExecuteJob` to `ExecutionRecord` (FR#6)

**Integration tests:**
- POST `/api/scheduler/jobs/{job_id}/trigger` — returns 202 for active job (FR#1)
- POST with unknown `job_id` — returns 409 (FR#2)
- POST with still-pending one-shot job — returns 202, executes, and dequeues from heap (FR#3)
- POST with single-mode guard held — returns 409 (FR#4)
- POST with restart-mode guard held — returns 202 and dispatches (FR#4, FR#5)
- POST with queued-mode guard held — returns 202 and dispatches (FR#4, FR#5)
- POST with parallel-mode job — returns 202 regardless of guard state (FR#5)
- Verify `trigger_mode="manual"` in execution record after trigger (FR#6)
- WebSocket `execution_completed` fires for manual trigger — covered by existing WS infrastructure tests; no new test needed (FR#7)
- POST with RuntimeError during dispatch — returns 500 with error detail

**Frontend tests:**
- `JobDetail` renders "Run Now" button (FR#8)
- Button enters loading state on click and disables (FR#11)
- Error message renders on 409 and 500 responses (FR#8)
- Execution table renders "manual" badge when `trigger_mode` is present (FR#9)
- Detail panel renders trigger_mode when present (FR#10)

### Tests to Remove

No tests to remove.

## Documentation Updates

- **modify** `docs/pages/web-ui/debug-handler.md` — mention the "Run Now" button in the job detail panel walkthrough and the "manual" badge in the execution table
- **regenerate** `docs/_static/web_ui_app_detail_handlers.png` — the handlers tab screenshot now includes the "Run Now" button; regenerate via `uv run python scripts/capture_screenshots.py --only web_ui_app_detail_handlers`

## Impact

### Changed Files

<!-- Gap check 2026-07-06: 1 gap included — frontend/src/test/handlers.ts (MSW POST handler) → T03 Focus -->

- **modify** `src/hassette/commands.py` — add `trigger_mode: str | None = None` field to `ExecuteJob`
- **modify** `src/hassette/core/scheduler_service.py` — add `trigger_now(db_id)` method; add `trigger_mode` parameter to `run_job_with_guard()` and `run_job()`, threading it through from the route handler to the `ExecuteJob` command
- **modify** `src/hassette/core/command_executor.py` — read `cmd.trigger_mode` in `build_record()` for `ExecuteJob` case
- **modify** `src/hassette/web/models.py` — add `JobTriggerResponse` model
- **modify** `src/hassette/web/routes/scheduler.py` — add POST `/jobs/{job_id}/trigger` endpoint
- **modify** `frontend/src/api/endpoints.ts` — add `triggerJob()` function
- **modify** `frontend/src/components/app-detail/job-detail.tsx` — add "Run Now" button to `extras` prop
- **modify** `frontend/src/components/shared/execution-table.tsx` — render "manual" badge in execution rows
- **modify** `frontend/src/components/shared/detail-panel.tsx` — render `trigger_mode` as a standalone line item, independent of the `trigger_context_id`-gated context block
- **create** `tests/unit/core/test_scheduler_service_trigger.py` — unit tests for `trigger_now()`
- **create** `tests/integration/web_api/test_trigger_job.py` — integration tests for trigger endpoint
- **modify** `tests/unit/core/test_command_executor.py` — test `trigger_mode` propagation in `build_record()`
- **create** `frontend/src/components/app-detail/job-detail.test.tsx` — frontend component tests (or modify if exists)
- **modify** `frontend/src/components/shared/execution-table.test.tsx` — test manual badge rendering
- **regenerate** `openapi.json` — new `JobTriggerResponse` model and POST endpoint
- **regenerate** `frontend/src/api/generated-types.ts` — TypeScript types from updated OpenAPI schema
- **modify** `docs/pages/web-ui/debug-handler.md` — mention "Run Now" button and "manual" badge
- **regenerate** `docs/_static/web_ui_app_detail_handlers.png` — screenshot includes new button

### Behavioral Invariants

- Recurring job timing must not change after a manual trigger — the job's next scheduled fire time remains unaffected. One-shot jobs are dequeued before dispatch to prevent double execution
- Existing `execution_completed` WebSocket message format must not change — only the `trigger_mode` field (already in the schema) gets populated
- `ExecuteJob` construction sites that don't pass `trigger_mode` must continue to work (field defaults to `None`)
- `build_record()` for `InvokeHandler` commands must not be affected

### Blast Radius

- **OpenAPI schema** — regenerated with new `JobTriggerResponse` model and endpoint
- **Generated TypeScript types** — regenerated from updated OpenAPI schema
- **WebSocket schema** — unchanged (no new message types)

## Open Questions

None — all design decisions resolved during discovery.
