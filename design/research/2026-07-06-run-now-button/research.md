---
proposal: "Add a 'Run Now' button for scheduled jobs on the app detail page, with a POST endpoint to trigger immediate execution and frontend feedback."
date: 2026-07-06
status: Draft
flexibility: Exploring
motivation: "User-facing feature gap — the UI shows scheduled jobs with no way to manually trigger them. Debugging/dev need plus ecosystem parity with Airflow/n8n/Prefect."
constraints: "Layer 1 only (zero-param trigger, no parameter override UI). Let research decide on execution feedback model."
non-goals: "Schema-driven override forms (Layer 2, future). No JSON input."
depth: deep
---

# Research Brief: Run Now Button for Scheduled Jobs

**Initiated by**: Issue #346 — add a UI control to trigger immediate execution of a scheduled job without waiting for its next scheduled run time.

## Context

### What prompted this

The hassette web UI displays scheduled jobs with full execution history, stats, and next-run times, but provides no way to manually trigger a job. Every surveyed peer framework (Airflow, n8n, Prefect, Temporal) offers "run now" from the UI. The prior art research at `design/research/2026-05-02-frontend-exposure-interactivity/research.md` explicitly calls this out as gap #1: "No manual trigger capability — every surveyed framework offers 'run now' from the UI."

Issue #346's comment from the repo owner recommends a layered approach: Layer 1 (this issue) is a simple zero-param "Run Now" button via `POST /api/apps/{app_key}/jobs/{job_id}/trigger`. Layer 2 (future) is schema-driven override forms. The comment explicitly says: do NOT require JSON input for Layer 1.

### Current state

**Backend execution path.** When a scheduled job's fire time arrives, `SchedulerService.serve()` pops it from the heap, spawns `dispatch_and_log(job)` via `task_bucket`. That method computes the next occurrence, re-enqueues recurring jobs, then calls `run_job_with_guard(job)` which routes through the `ExecutionModeGuard` (for single/restart/queued overlap semantics) before calling `run_job(job)`. `run_job` constructs an `ExecuteJob` command (frozen dataclass in `src/hassette/commands.py`) and delegates to `CommandExecutor.execute(cmd)`, which runs the callable with timeout enforcement and records an `ExecutionRecord` to the write queue.

**No public trigger method exists.** `SchedulerService.trigger_due_jobs()` fires all currently-due jobs but is explicitly documented as "intended for controlled test dispatch" and operates on heap time, not by job ID. There is no `trigger_now(job_id)` or equivalent.

**Job lookup.** Jobs live on a heap (`_ScheduledJobQueue`) ordered by fire time. The only lookup path is `get_all_jobs()` which returns a full snapshot. There is no `get_job_by_id()` method. The `enrich_jobs_with_heap` utility in `src/hassette/web/utils.py` builds a `{db_id: job}` dict from the full snapshot for enrichment — the same pattern would work for trigger lookup.

**`trigger_mode` field.** The `trigger_mode` column exists in the `executions` table (migration `001.sql`, line 102), flows through `ExecutionRecord` (line 104), `TelemetryRepository` (insert and select), `Execution` Pydantic model (line 125), OpenAPI schema, and generated TypeScript types. However, it is **never populated** — always `None` at runtime. The `ExecutionRecord` docstring explicitly marks it as "reserved for future trigger-mode tracking." Issue #648 tracks populating it. The `ExecuteJob` command dataclass does not carry a `trigger_mode` field.

**Existing action endpoints.** Three POST endpoints exist for app actions in `src/hassette/web/routes/apps.py`: `/api/apps/{app_key}/start`, `.../stop`, `.../reload`. All return `ActionResponse(status="accepted", app_key=app_key, action="...")` with HTTP 202. Error handling catches `(ValueError, RuntimeError)` and raises `HTTPException(status_code=500)`. Validation uses `_validate_app_key()` (400) and `_require_known_app()` (404).

**Scheduler routes.** `src/hassette/web/routes/scheduler.py` has a single `GET /api/scheduler/jobs` endpoint. No action endpoints exist for jobs.

**Frontend.** Jobs are displayed in two places: the app detail page's "handlers" tab (via `HandlersTab` which shows both listeners and jobs in a master-detail layout), and the global `/handlers` page (a unified table of all listeners and jobs). Neither has action buttons for jobs. The `ActionButtons` component handles app start/stop/reload only. The toast system (sonner) exists but is underutilized — `ActionButtons` shows errors inline rather than via toast.

**WebSocket feedback.** The `execution_completed` WS message already covers job executions (`kind="job"`, `job_id` field). The frontend auto-invalidates execution tables when this signal fires with a matching `job_id`. This means a manually triggered job's completion would automatically appear in the execution history without additional WebSocket work.

### Key constraints

- **Layer 1 scope only**: zero-param trigger, no parameter override UI.
- **`trigger_mode` must be populated as `"manual"`** for manually triggered executions (per issue comment). This requires changes to the `ExecuteJob` command and `CommandExecutor.build_record()`.
- **Must not affect scheduled timing**: triggering a job manually must not change its next scheduled run time. The job continues on its normal schedule.
- **Must respect `ExecutionModeGuard`**: a manual trigger should honor the job's overlap semantics (single/restart/queued/parallel). If a job is in `SINGLE` mode and already running, the manual trigger should be suppressed — not bypass the guard.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| `SchedulerService` — add `trigger_now(db_id)` | 1 file | Low | Medium — must not disrupt heap state or scheduled timing |
| `ExecuteJob` command — add `trigger_mode` field | 1 file | Low | Low — frozen dataclass, additive change |
| `CommandExecutor.build_record()` — propagate `trigger_mode` | 1 file | Low | Low — existing field, just needs population |
| New POST route in scheduler routes | 1-2 files | Low | Low — follows established pattern |
| New response model (or extend `ActionResponse`) | 1 file | Low | Low |
| Frontend: trigger button in job detail | 2-3 files | Medium | Low — established patterns exist |
| Frontend: API endpoint function | 1 file | Low | Low |
| Tests: backend trigger path | 2-3 files | Medium | Low |
| Tests: frontend component | 1-2 files | Medium | Low |
| OpenAPI schema regeneration | Generated | Low | Low |

### What already supports this

1. **`trigger_mode` is fully plumbed.** The field exists in the DB schema, `ExecutionRecord`, the Pydantic response model, the OpenAPI spec, and the generated TypeScript types. It round-trips through persistence and queries. The only missing piece is populating it.

2. **`run_job()` is the reusable execution core.** `SchedulerService.run_job(job)` constructs the `ExecuteJob` command with all the right context (timeout, error handler, async adapter) and delegates to `CommandExecutor`. A `trigger_now()` method can call `run_job_with_guard(job)` to get the full execution path including overlap semantics, or `run_job(job)` directly for parallel-only execution.

3. **`execution_completed` WebSocket message covers jobs.** No new WS message type is needed. When the manually triggered job completes, the existing `execution_completed` signal fires with `kind="job"` and the `job_id`, causing the frontend to auto-invalidate the execution table. The user sees the result appear in real time.

4. **`ActionButtons` provides the UI pattern.** Loading state via `useSignal(false)`, error display inline, async `exec()` wrapper, disabled state during execution. The job trigger button can follow the same pattern.

5. **`SchedulerDep` is already available.** The dependency alias for `SchedulerService` exists in `src/hassette/web/dependencies.py`, ready for injection into new route handlers.

6. **Job enrichment shows the lookup pattern.** `enrich_jobs_with_heap` builds a `{db_id: ScheduledJob}` dict from `get_all_jobs()`. The same approach works for finding a job by `db_id` in a trigger endpoint.

### What works against this

1. **No `get_job_by_id()`.** The scheduler heap has no index by `db_id`. Finding a specific job requires `get_all_jobs()` and scanning. For the number of jobs in a typical hassette instance (tens, not thousands), this is not a performance concern, but it is a missing abstraction.

2. **`dispatch_and_log` couples scheduling with execution.** The normal path through `dispatch_and_log` computes the next occurrence and re-enqueues. A manual trigger must bypass this — it should execute the job without touching the schedule. This means calling `run_job_with_guard(job)` or `run_job(job)` directly, not going through `dispatch_and_log`.

3. **`ExecuteJob` has no `trigger_mode` field.** The command dataclass needs a new field. This is a small change but touches the command → executor → record-building pipeline.

4. **One-shot jobs may have already fired and been removed from the heap.** A job registered with `After(5)` or `Once(time)` fires once and is removed. It exists in the DB (`scheduled_jobs` table) but not on the live heap. A "Run Now" for a one-shot job that has already fired is ambiguous — the callable may no longer be available in memory.

## Options Evaluated

### Option A: Fire-and-forget with WebSocket feedback (recommended by existing patterns)

**How it works**: A new `POST /api/scheduler/jobs/{job_id}/trigger` endpoint looks up the live `ScheduledJob` on the heap by `db_id`, calls `scheduler_service.trigger_now(job_id)` which spawns the job through `run_job_with_guard()` (respecting overlap semantics) and returns immediately. The endpoint returns HTTP 202 with a response confirming the trigger was accepted. Execution feedback arrives via the existing `execution_completed` WebSocket message.

On the backend, `SchedulerService.trigger_now(db_id)` does:
1. `get_all_jobs()` to snapshot the heap.
2. Find the job with matching `db_id`. Return 404 if not found (job is one-shot and already fired, or app is not running).
3. Spawn `run_job_with_guard(job)` via `task_bucket.spawn()` — this respects `ExecutionModeGuard` for overlap.
4. Return immediately (fire-and-forget from the HTTP perspective).

The `trigger_mode="manual"` value is threaded through: `trigger_now()` passes it to `run_job()`, which includes it on the `ExecuteJob` command, and `build_record()` reads it onto the `ExecutionRecord`. This populates the existing DB column for manual executions without affecting scheduled ones (which would continue to use `None` or a future `"schedule"` value).

On the frontend, a "Run Now" button appears in `JobDetail` (the expanded job view on the handlers tab). The button uses the same `exec()` + loading signal pattern as `ActionButtons`. After clicking, the button shows a spinner. When `execution_completed` fires with the matching `job_id`, the execution table auto-updates and the user sees the result. No additional polling is needed.

**Where the button appears:**
- **App detail page, handlers tab, job detail panel**: Primary location. The button sits in the `HandlerDetailLayout` extras area alongside existing stats. This is where the user is already looking at a specific job.
- **Global `/handlers` page**: The unified table currently has no per-row actions. Adding a trigger icon button in a new "actions" column is feasible but adds visual noise to a dense table. This could be a fast follow rather than part of Layer 1.

**Pros**:
- Reuses the established 202/fire-and-forget pattern from app actions.
- Execution feedback is free via existing WebSocket infrastructure — no new message types.
- Overlap semantics are respected (single-mode jobs won't double-fire).
- The `trigger_mode` plumbing already exists end-to-end.
- Minimal new code — one new method on `SchedulerService`, one new route, one frontend button.

**Cons**:
- No immediate success/failure feedback in the HTTP response. The user sees "accepted" but must wait for the WS message to know if the job succeeded. For fast jobs (< 1s), this is nearly instant. For slow jobs, the user must watch the execution table.
- If the job is suppressed by `ExecutionModeGuard` (single-mode, already running), the user gets a 202 "accepted" but nothing happens. The suppression is silent from the HTTP perspective.

**Effort estimate**: Small. One backend method + one route + one frontend button + tests. All patterns exist and are well-established.

**Dependencies**: None new. All tooling is already in the stack.

### Option B: Synchronous execution with inline result

**How it works**: The POST endpoint awaits the job execution and returns the result (success/error/timeout) in the HTTP response body. Instead of 202, it returns 200 with an execution summary.

On the backend, `trigger_now()` awaits `run_job_with_guard(job)` instead of spawning it. The endpoint returns after the job completes, with the execution status in the response.

On the frontend, the button shows a spinner for the full duration of the job, and the response tells the user immediately whether it succeeded or failed.

**Pros**:
- Direct feedback — the user knows the outcome without waiting for WS.
- Guard suppressions can be reported in the response (e.g., "job was suppressed because another execution is in progress").
- Simpler frontend — no need to correlate the trigger action with a WS event.

**Cons**:
- Long-running jobs block the HTTP connection. A job with a 30s timeout holds the connection open for 30s. The frontend needs a generous fetch timeout.
- Ties up a FastAPI worker for the duration of the job execution. For hassette's scale this is acceptable (single user, few concurrent requests), but it is architecturally worse than fire-and-forget.
- The existing app action pattern uses 202 fire-and-forget. Synchronous execution would be a new pattern, creating inconsistency.
- Guard suppression reporting requires `run_job_with_guard` to return a result status, which it currently does not (it is a void async method). The guard's `try_acquire` → `SUPPRESSED`/`QUEUED_ACCEPTED` flow is internal to `execution_mode.py` and does not surface to the caller.

**Effort estimate**: Medium. Same backend/frontend work as Option A, plus: modifying `run_job_with_guard` to return an outcome enum, adding a timeout wrapper to the endpoint, creating a new response model with execution details.

**Dependencies**: None new.

### Option C: Hybrid — 202 with guard feedback

**How it works**: The endpoint returns 202 for fire-and-forget execution (like Option A), but checks the guard state before dispatching. If the job is in `SINGLE` mode and the guard is currently held, the endpoint returns 409 Conflict with a message explaining why the job cannot be triggered. If the guard is free, it spawns the execution and returns 202.

This gives immediate feedback for the most common failure case (overlap suppression) without blocking on job execution.

**Pros**:
- Best of both: fast 202 response for the happy path, clear error for the overlap case.
- Consistent with the fire-and-forget pattern.
- No long-lived HTTP connections.
- Guard check is synchronous and cheap (reading a boolean).

**Cons**:
- Race condition: the guard could be acquired between the check and the dispatch. In practice, this window is negligible for a single-user system, but it means the 202 is still not a guarantee of execution.
- Requires exposing the guard's busy state, which is currently encapsulated inside `run_through_guard()`. The `ExecutionModeGuard` has a `try_acquire` method that returns `ACQUIRED`/`SUPPRESSED`/`QUEUED_ACCEPTED` — this could be checked before spawning.
- Adds complexity for a case that may be rare in practice (how often does a user manually trigger a job that is already running?).

**Effort estimate**: Small-to-Medium. Option A's work plus a pre-dispatch guard check and a 409 response path.

**Dependencies**: None new.

## Concerns

### Technical risks

- **One-shot jobs disappear from the heap after firing.** A `run_in(my_task, 5)` job fires after 5 seconds and is removed from the heap and the `_jobs_by_name` dict. It still exists in the `scheduled_jobs` DB table, so the UI shows it, but `trigger_now()` cannot find it on the heap. The endpoint must return a clear error (404 with a message like "job has already completed and is no longer active"). This is not a bug but requires explicit handling and frontend messaging.

- **Guard interaction for manual triggers.** If a job uses `SINGLE` execution mode and is already running from its scheduled fire, a manual trigger will be suppressed by the guard. The user clicks "Run Now" and nothing visible happens. Option C addresses this with a pre-check, but even Options A and B need to communicate this possibility in the UI (tooltip, documentation, or a "job is currently running" indicator).

- **Concurrent trigger requests.** Two rapid clicks on "Run Now" could dispatch two executions for a `PARALLEL`-mode job. The frontend should disable the button during the request, and the backend spawn is idempotent from a data perspective (each execution gets its own record), so this is a UX concern rather than a data integrity risk.

### Complexity risks

- **New field on `ExecuteJob`.** Adding `trigger_mode` to the frozen command dataclass is safe (it is additive), but every construction site for `ExecuteJob` must be updated to pass it. Currently there is only one: `SchedulerService.run_job()`. The `trigger_now()` method would be a second construction site, or `run_job()` would accept an optional `trigger_mode` parameter.

- **`trigger_mode` semantics for handlers.** Issue #648 defines `trigger_mode` values as `event/schedule/manual/retry`. If this PR populates `trigger_mode="manual"` for jobs, it sets a precedent for the field's values. The handler side (bus invocations) would still be `None`. This partial population is acceptable — the field is explicitly documented as "reserved, populated incrementally" — but should be noted in the PR description.

### Maintenance risks

- **Layer 2 migration path.** The zero-param trigger endpoint needs to remain backward-compatible when Layer 2 adds parameter overrides. The endpoint path `POST /api/scheduler/jobs/{job_id}/trigger` is parameter-free today. Layer 2 could add an optional JSON body with override params without changing the URL. The request body should be optional from the start (no required fields) so the upgrade is additive.

## Open Questions

- [ ] **Should the button appear on the global `/handlers` page too, or only on the app detail job panel?** The global page is a dense table; adding an actions column changes its layout. The app detail view is the natural home for "Run Now" since the user is already focused on a specific job. The global page could be a fast follow.

- [ ] **What should happen when a user triggers a one-shot job that has already fired?** The job's callable exists in the `scheduled_jobs` DB table but is no longer on the live heap. Options: (a) return 404 "job is no longer active", (b) return 409 "one-shot job has already completed", (c) attempt to re-run from the DB record (requires reconstructing the callable — not feasible without the live app context). Option (a) or (b) seems correct.

- [ ] **Should `trigger_mode` become an enum or stay a free-form string?** The field is currently `str | None`. Issue #648 suggests values `event/schedule/manual/retry`. An enum provides type safety and prevents typos. A string allows future extensibility without migrations. The DB column has no CHECK constraint. Given that #648 defines a closed set of four values, an enum in Python code (with string storage in SQLite) is the stronger choice.

- [ ] **Should issue #648 (populating `trigger_mode` for all execution types) be done as part of this work or separately?** This issue only needs `trigger_mode="manual"` for manual triggers. Populating `"schedule"` for scheduled fires and `"event"` for bus invocations is orthogonal work. Doing #648 first would be cleaner (establish the enum, update all write paths), but #346 can stand alone by populating only the manual case.

## Recommendation

This feature is well-supported by the existing architecture. The `trigger_mode` plumbing, `execution_completed` WebSocket messages, and `ActionButtons` UI pattern make this a straightforward addition. The main implementation risk is low.

**Option A (fire-and-forget with WS feedback)** is the strongest choice. It follows the established app-action pattern (202 + WebSocket state update), avoids blocking HTTP connections, and leverages the existing `execution_completed` infrastructure for free. The user experience is good: click "Run Now", see a spinner, watch the execution appear in the history table within seconds.

Option C (hybrid with guard pre-check) is a reasonable enhancement if guard suppression proves confusing in practice, but adds complexity for a case that is likely rare. It could be added later if user feedback warrants it.

Option B (synchronous) is the weakest choice — it introduces a new HTTP pattern, blocks connections, and gains little over Option A given the existing WebSocket feedback loop.

**Start with the button on the app detail page only.** The global handlers table is summary-oriented; per-row actions would change its character. Add it there in a follow-up if users ask for it.

### Suggested next steps

1. Write a design doc via `/mine-define` covering the backend `trigger_now()` method, the POST endpoint, the `trigger_mode` threading, and the frontend button placement.
2. Decide whether to do #648 (full `trigger_mode` population) as a prereq or leave it for later.
3. Implement Layer 1: backend endpoint + frontend button + tests.

## Sources

- [Airflow AIP-50: Trigger DAG UI Extension with Flexible User Form Concept](https://cwiki.apache.org/confluence/display/AIRFLOW/AIP-50+Trigger+DAG+UI+Extension+with+Flexible+User+Form+Concept)
- [Airflow DAG Run Status documentation](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dag-run.html)
- [FastAPI Background Tasks documentation](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [10 FastAPI Background Patterns That Don't Block](https://medium.com/@connect.hashblock/10-fastapi-background-patterns-that-dont-block-cbfea8bfb717)
