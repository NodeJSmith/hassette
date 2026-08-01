# Design: Registered and Manual Jobs

**Date:** 2026-07-30
**Status:** archived
**Scope-mode:** hold
**Research:** `design/research/2026-07-30-trigger-agnostic-job-execution/research.md`

## Problem

Hassette currently treats presence in the scheduler heap as proof that a job exists. That prevents a registered job from existing without an automatic occurrence. `EntityTime` works around the limitation with a year-9999 sentinel, completed one-shots disappear from live runtime state, and app authors who need manually invoked work must create a fake far-future schedule.

Manual execution is also coupled to heap membership. The Python API has no manual-only registration, while the web Run Now route can address only jobs found in the heap and changes pending one-shot schedules when invoked.

The scheduler needs to distinguish a live job registration from its optional automatic schedule without becoming a generic workflow or result-processing platform.

## Goals

- Allow app authors to register named manual-only jobs without a fake trigger or timestamp.
- Keep scheduled, waiting, completed, and manual jobs live, inspectable, removable, and manually submit-capable while their app is running.
- Make the due-time heap represent only concrete automatic occurrences.
- Give Python, API, CLI, and UI manual submission one fire-and-observe contract.
- Use truthful schedule status and timing in operator surfaces.
- Replace ambiguous registration cancellation terminology with removal while retaining cancellation for interrupted executions.
- Preserve existing overlap, timeout, error handling, task ownership, telemetry, and dependency-injection behavior.

## Non-Goals

- Bus handler registration or manual Bus invocation.
- Reusable executable definitions shared across trigger sources.
- Waiting for manual invocation, callable result propagation, invocation handles, or execution result objects.
- Per-submission args or kwargs.
- New execution queues, retry semantics, durable delivery, or exactly-once guarantees.
- Generalizing `TriggerProtocol` for arbitrary recoverable triggers.

## User Scenarios

### App author: Register and submit manual work
- **Goal:** Expose side-effecting app work for manual invocation without inventing a schedule.
- **Context:** The app owns an operation that should run only when requested from code or an operator surface.

#### Register and submit

1. **Register the job**
   - Sees: `scheduler.register(...)` with the same execution-policy options as scheduled jobs, excluding schedule-only options.
   - Decides: Stable name, group, mode, timeout, error handler, and fixed args/kwargs.
   - Then: Receives a live `Job` with `schedule_status == "manual"` and a valid database ID.
2. **Submit an invocation**
   - Sees: `job.submit()` as a synchronous fire-and-observe operation.
   - Decides: Whether to request the side effect now.
   - Then: Hassette submits through the existing overlap guard, task bucket, executor, telemetry, and error handling; the method returns `None` immediately.
3. **Observe the outcome**
   - Sees: Existing execution telemetry, logs, and configured error handlers.
   - Decides: Whether operational follow-up is needed.
   - Then: No result object or callable return value is exposed.
4. **Remove the registration**
   - Sees: `job.remove()`, `scheduler.remove_job()`, and group removal.
   - Decides: When the job should no longer be manually or automatically invocable.
   - Then: Future submissions through the stale handle raise `JobRemovedError`; active and queued executions are cancelled or dropped.

### Operator: Inspect and submit any live job
- **Goal:** Understand whether a job has an automatic schedule and request an immediate run.
- **Context:** The operator uses the web UI or CLI while the owning app is running.

#### Inspect and submit

1. **Inspect the job**
   - Sees: `scheduled`, `waiting`, `completed`, or `manual`, plus a next-run time only when one exists.
   - Decides: Whether manual submission is appropriate.
   - Then: Waiting, completed, and manual states explain why no timestamp appears.
2. **Submit the job**
   - Sees: Run Now available for every live job.
   - Decides: Submit once.
   - Then: The API returns accepted for a live registration; overlap suppression or queue drops are visible only through telemetry.

## Functional Requirements

- **FR#1** `Scheduler.register()` must create a live manual-only `Job` with a required stable name and valid persisted job ID before the awaited call returns.
- **FR#2** `Scheduler.register()` must accept group, timeout, timeout disabling, execution mode, error handler, fixed args/kwargs, and `if_exists`, but not trigger, jitter, or predicate options.
- **FR#3** Scheduled APIs and `Scheduler.register()` must return one public `Job` type; `ScheduledJob` must no longer be the public runtime type.
- **FR#4** Every live job must expose `schedule_status` as exactly `scheduled`, `waiting`, `completed`, or `manual`.
- **FR#5** A service-level live registry must make jobs addressable independently of heap membership.
- **FR#6** The due-time heap must contain only jobs with a concrete automatic occurrence.
- **FR#7** An `EntityTime` job without a resolvable occurrence must be `waiting`, stay registered and watched, and remain outside the heap.
- **FR#8** An `EntityTime` job must move between `waiting` and `scheduled` when its entity value becomes invalid or valid without losing registration or missing a change during setup.
- **FR#9** A job whose final automatic occurrence is consumed must become `completed` regardless of predicate, overlap, or execution outcome and must remain live.
- **FR#10** A manual-only job must be `manual`, have no heap entry, and persist truthful non-time-trigger metadata.
- **FR#11** `Job.submit()` must synchronously submit one manual invocation and return `None` without accepting per-invocation arguments.
- **FR#12** Manual submission must use the job's registered args/kwargs, bypass its predicate, preserve its automatic schedule, and record manual trigger telemetry.
- **FR#13** Manual submission must preserve existing execution-mode behavior; suppression and queue-drop outcomes must not be synchronously returned.
- **FR#14** API, CLI, and UI submission must use the same service submission path as `Job.submit()`.
- **FR#15** Remote submission of a live job must return accepted even when overlap policy later suppresses or drops the invocation.
- **FR#16** Submitting through a removed `Job` handle must raise `JobRemovedError`; remote submission of a persisted but non-live job must return HTTP 409.
- **FR#17** Manual submission must not consume, move, or complete a pending automatic occurrence, including a pending one-shot.
- **FR#18** The public removal APIs must be `Job.remove()`, `Scheduler.remove_job()`, and `Scheduler.remove_group()`.
- **FR#19** Removing a job must remove its live registration, heap occurrence, group/name indexes, and trigger watcher; cancel active async execution; drop queued execution; reject future submission; and retain historical telemetry.
- **FR#20** `if_exists="replace"` must remove the old registration before registering the new one; replacement failure must leave no old registration and no partially live new registration.
- **FR#21** App shutdown and reload must remove every owned job, including waiting, completed, and manual jobs, and preserve reconciliation accuracy.
- **FR#22** Job summaries must expose `schedule_status` and nullable `next_run`; operator surfaces must distinguish waiting, completed, and manual instead of showing a fabricated or unexplained timestamp.
- **FR#23** Persisted registration removal must use `removed_at`; execution outcomes must continue using `cancelled` only for interrupted executions.
- **FR#24** Ordinary trigger completion remains defined by `next_run_time()` returning `None` after an occurrence; existing first-occurrence and `if_past` behavior must not change.
- **FR#25** Job summaries must expose nullable `schedule_status_reason`; trigger calculation failures must persist and render `trigger_error` without adding another schedule-status value.
- **FR#26** The frontend Run Now button must surface post-submission feedback: poll for a new execution record after submission, show a success toast when one appears, or show "No execution recorded" if nothing appears within a reasonable timeout. Suppressed/dropped invocations never create an execution record, so the timeout fallback is the only signal for those outcomes in this initial implementation. A follow-up issue should add a submission correlation ID so the toast can be reliably linked to the specific invocation rather than racing concurrent executions.

## Edge Cases

- An `EntityTime` source becomes valid between the initial state read and watcher installation. The post-registration reconciliation read must activate the correct occurrence.
- An `EntityTime` source becomes invalid while its job is on the heap. The heap entry is removed without removing the registration or watcher.
- An entity update arrives while its job is popped for dispatch. Existing pending-reschedule protection must avoid duplicate heap entries and settle on the latest source time.
- A pending one-shot is submitted manually. It runs manually and still fires automatically at its original time.
- A completed one-shot is submitted repeatedly. Every accepted request follows the same overlap policy while the schedule remains completed.
- A live `single` job is already running or a `queued` job is full. Submission returns normally/accepted and telemetry records suppression or drop.
- A `restart` submission cancels the current execution; a `parallel` submission starts independently.
- A job is removed while popped, running, or holding queued requests. Removal prevents re-enqueue, releases the guard, drains completion futures, and makes the handle stale.
- A sync handler is active during removal. Hassette cancels its awaiting task but does not claim to terminate the worker thread or reverse side effects.
- Persistence succeeds but a later registration step fails. No registry, heap, per-app index, group, or watcher residue remains.
- Destructive replacement removes the old job and then the new registration fails. The name remains unregistered and the error propagates.
- A stale persisted ID is submitted during or after app reload. It receives 409 unless a live job with that ID has completed registration.
- Manual-only trigger metadata must not masquerade as cron, interval, one-shot, or custom-trigger scheduling.

## Acceptance Criteria

- **AC#1** Backend tests demonstrate that `await scheduler.register(...)` returns a persisted `Job` with manual status and no heap entry. Covers FR#1-FR#6 and FR#10.
- **AC#2** Backend tests demonstrate waiting EntityTime registration, invalid/valid transitions, watcher cleanup, and registration-time race reconciliation without `NO_OCCURRENCE`. Covers FR#7-FR#8.
- **AC#3** Backend tests demonstrate that one-shots become completed but remain submit-capable and that manual submission does not consume pending automatic occurrences. Covers FR#9 and FR#17.
- **AC#4** Backend tests demonstrate `submit()` behavior for all execution modes, fixed arguments, predicate bypass, manual telemetry, and removed-handle errors. Covers FR#11-FR#16.
- **AC#5** Backend tests demonstrate complete removal and destructive replacement cleanup across registry, heap, indexes, watchers, guards, and persisted `removed_at`. Covers FR#18-FR#21 and FR#23.
- **AC#6** Migration tests upgrade existing databases from `cancelled_at` to `removed_at` without losing timestamps or breaking active-registration queries. Covers FR#23.
- **AC#7** API and CLI tests demonstrate all four schedule statuses, nullable next-run rendering including scheduled-but-timing-unavailable degraded responses, accepted live submissions, and 409 for non-live persisted jobs. Covers FR#14-FR#16 and FR#22.
- **AC#8** Frontend tests demonstrate distinct scheduled/waiting/completed/manual rendering and Run Now availability for every live status. Covers FR#14 and FR#22.
- **AC#9** Playwright E2E demonstrates a manual-only job displayed and submitted through the live UI with execution activity subsequently visible. Covers FR#10, FR#14, and FR#22.
- **AC#10** Existing scheduler unit, integration, and system suites pass after public type/removal API migrations, and `prek -a` passes. Covers FR#3, FR#19, FR#21, and FR#24.
- **AC#11** Backend and API tests demonstrate that a raising recurrence calculation leaves the current due occurrence executable, persists `completed` with reason `trigger_error`, and exposes that reason in normal and degraded summaries. Covers FR#9, FR#22, and FR#25.
- **AC#12** Migration/API tests demonstrate legacy rows use the `legacy_unknown` reason, removed legacy rows stay excluded from active lists, operator surfaces render the unknown state explicitly, and live re-registration replaces the placeholder status and clears the reason. Covers FR#22, FR#23, and FR#25.
- **AC#13** Frontend tests demonstrate that the Run Now button surfaces a success toast when an execution record appears after submission, and a "No execution recorded" fallback toast after timeout, for all live statuses (scheduled, waiting, completed, and manual-only jobs). Covers FR#26.

## Key Constraints

- Do not add a generic execution service, executable registry, producer adapter layer, or request queue.
- Do not refactor Bus registration or invocation behavior. The `listeners.cancelled_at` → `removed_at` column rename is a mechanical terminology correction applied alongside the same rename on `scheduled_jobs`, not a Bus behavioral change.
- Do not expose callable return values, waiting invocation, invocation handles, or execution result objects.
- Do not add per-submission arguments or predicate override flags.
- Do not infer live registration from heap membership.
- Do not encode waiting as a far-future timestamp.
- Do not combine registration, schedule, and execution into one runtime state enum.
- Do not retain compatibility aliases for the `ScheduledJob` or cancellation API names unless a concrete external compatibility requirement emerges before implementation.

## Dependencies and Assumptions

- Home Assistant state events remain the source for `EntityTime` reactivation.
- The existing local Web API access model is unchanged; this design adds no authentication boundary.
- Registration args and kwargs retain their existing telemetry persistence and personal-data sensitivity.
- `CommandExecutor`, `ExecutionModeGuard`, `TaskBucket`, and `SyncExecutor` remain the execution foundation.
- Generated TypeScript types continue to come from the FastAPI OpenAPI schema.
- The project supports backend unit/integration/system tests, frontend Vitest tests, and Playwright E2E tests.

## Architecture

### One Scheduler-Owned Job

Rename `ScheduledJob` in `src/hassette/scheduler/classes.py` to `Job`. Both `Scheduler.schedule()` and new `Scheduler.register()` construct this type. Do not introduce manual and scheduled subclasses: ownership, invocation policy, telemetry identity, grouping, removal, and execution are identical.

`Job` stores one schedule axis:

```python
class ScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    WAITING = "waiting"
    COMPLETED = "completed"
    MANUAL = "manual"
```

Live `Job.schedule_status` is authoritative for future automatic scheduling availability. `next_run` and `fire_at` become optional on the job but are required for heap insertion when `schedule_status is SCHEDULED`. All schedule-status transitions route through one shared `Job.transition_to(status, *, next_run=None, fire_at=None, reason=None)` method that enforces the pairing centrally: `SCHEDULED` requires concrete timing, all other statuses clear timing fields, and `schedule_status_reason` is always set (or cleared to `None`) through this method rather than by direct field assignment. This prevents a stale `next_run` surviving on a `COMPLETED` or `WAITING` job when a transition site forgets to clear it independently. When the final occurrence is popped, its concrete timing is copied into local dispatch context before the job transitions to completed; predicate evaluation, lag calculation, and execution use that dispatch-local occurrence timing. `sort_index` is assigned only when a concrete occurrence is set. This keeps nullable timing localized to the job boundary; `_ScheduledJobQueue.add()` rejects any job that is not scheduled or lacks concrete timing, so heap comparison never sees missing timestamps.

Status transitions are narrow:

```text
manual -------------------------------> removed
waiting <------ EntityTime ------> scheduled
scheduled -- finite trigger ends --> completed
scheduled -- recurring next run ---> scheduled
waiting/completed/manual/scheduled --> removed
```

Removal is represented by absence from the live registry, not another `ScheduleStatus` value. Execution activity remains in `ExecutionModeGuard` and telemetry, not in schedule status.

### Registry Separate From Heap

Add `SchedulerService._jobs_by_id: dict[int, Job]`. It is the service-level authority for live runtime existence and O(1) API lookup. Add jobs only after persistence assigns `db_id`; remove them only through the central registration-removal path. Every mutation of `_jobs_by_id` must be identity-checked (`if self._jobs_by_id.get(db_id) is job`) — the upsert's natural-key reuse means an orphaned `Job` from a crash-restart cycle can share a `db_id` with a freshly re-registered live `Job`, so an unconditional removal keyed on `db_id` alone would silently unregister the live job. The same identity guard applies to the per-app `Scheduler`'s indexes (owned by `Scheduler`, not `SchedulerService`): `_jobs_by_name` and `_jobs_by_group` pops must confirm `self._jobs_by_name.get(job.name) is job` before removing.

Each structure has one responsibility:

| Structure | Responsibility |
|---|---|
| `SchedulerService._jobs_by_id` | Live runtime existence and ID lookup |
| `_ScheduledJobQueue` | Concrete due-time occurrences only |
| `Scheduler._jobs_by_name` | Per-owner stable-name identity and reconciliation IDs |
| `Scheduler._jobs_by_group` | Per-owner group operations |
| `Scheduler._entity_time_subs` | EntityTime watcher ownership |
| `scheduled_jobs` | Persisted registration and historical operator data |

`SchedulerService.get_all_jobs()` and live enrichment read the registry rather than the heap. A separate internal heap snapshot may remain only where timing diagnostics need it.

### Registration

Extract the common policy resolution and `Job` construction currently concentrated in `Scheduler.schedule()` so `schedule()` and `register()` cannot drift. `register()` remains a guarded awaited API with required `name=` and the same source-location capture used by other scheduler registrations.

Manual jobs use:

- `schedule_status=MANUAL`
- `trigger=None`
- `next_run=None`, `fire_at=None`
- no jitter or predicate
- persisted `trigger_type="manual"`, `trigger_label="Manual only"`, and `trigger_detail=NULL`

The migration extends the `scheduled_jobs.trigger_type` check constraint to include `manual`. Each trigger class defines its own `trigger_db_type() -> Literal[...]` method; `SchedulerService.add_job()` calls this when `job.trigger is not None`. For manual jobs (`job.trigger is None`), the existing "unreachable" `else` branch must set `trigger_type="manual"`, `trigger_label="Manual only"`, `trigger_detail=None`. `manual` is reserved for jobs created by `Scheduler.register()`; custom triggers continue using `custom`.

`SchedulerService.add_job()` performs this order:

1. Persist the registration and assign `db_id`.
2. Add the job to `_jobs_by_id`.
3. Enqueue only if status is scheduled.

The per-app `Scheduler` still owns name/group indexes before delegation, matching current collision behavior. `Scheduler._add_job()`'s call to `scheduler_service.add_job()` is wrapped in a try/except that, on any exception, calls the same removal helper used by `remove_job()` — passing the job even though it may never have reached the heap. This ensures that if enqueue fails after persist + registry succeed, the job is cleaned from registry, indexes, group membership, and watcher state rather than left addressable but absent from the heap. If persistence already produced a row ID, rollback sets `removed_at` so the failed registration cannot appear active; the row remains as registration history rather than requiring deletion and foreign-key special cases. Failures before persistence create no row.

`if_exists="replace"` intentionally calls the full removal path for the old job before creating the new registration. The replacement path must await the old job's removal persistence (not spawn it fire-and-forget) before issuing the new registration's upsert, because both target the same DB row via the natural key — spawning the removal write concurrently lets the new job's upsert reach the write queue first, and the old job's `removed_at` write then stamps removal onto the live row. There is no rollback to the old object after its guard and work have been cancelled.

### EntityTime Waiting

Remove `NO_OCCURRENCE` from `src/hassette/scheduler/triggers.py`. Replace it with a typed sentinel `WAITING` (from a small enum alongside `ScheduleStatus`, or a module-level constant with a distinct type) that both `first_run_time()` and `next_run_time()` can return to express "no occurrence right now, but I'm not exhausted." `first_run_time()` must support `WAITING` because the registration path (`Scheduler.schedule()`) calls `trigger.bind_state_reader()` then `trigger.first_run_time()` to determine initial scheduling — an `EntityTime` whose source entity is unavailable at registration time needs to produce `WAITING` here, not just at recurrence time. `dispatch_and_log()` matches on `next_run_time()`'s return type: concrete `ZonedDateTime` → scheduled, `None` → completed, `WAITING` → transition to waiting. `Scheduler.schedule()` binds the state reader and resolves initial state before delegating to `_add_job_and_watch_entity()`, which handles service registration, watcher setup, and post-registration reconciliation. Unavailable state at registration time constructs the job as waiting instead of assigning a timestamp.

Preserve the existing sequence:

1. Initial state resolution.
2. Job registration.
3. Framework Bus watcher registration.
4. Post-registration state re-read and reconciliation.

Replace `reschedule_job(job, next_run)` with schedule-transition operations that can activate with a concrete time or move to waiting. Replace `_pending_next_run` with a pending EntityTime transition that represents either a concrete activation time or waiting. Both transition kinds can race a popped occurrence; the implementation must keep only the latest entity-derived transition, apply it before trigger recurrence logic, and never enqueue the same `Job` twice.

### Completion

`SchedulerService.dispatch_and_log()` no longer removes one-shots or exhausted finite triggers. It computes the next schedule status before predicate/execution:

- Concrete next occurrence: update timing via `transition_to(SCHEDULED, next_run=..., fire_at=...)` and enqueue.
- `next_run_time()` returns `None`: `transition_to(COMPLETED)` and do not enqueue.
- Trigger returns a waiting indicator (only possible for `EntityTime`): `transition_to(WAITING)`, do not enqueue, do not mark completed, keep watcher active. This is the third leg of the branch that replaces `NO_OCCURRENCE` — without it, an EntityTime job whose entity becomes unavailable between occurrences would be incorrectly marked completed, losing its ability to reactivate when the entity yields a valid time again.
- Trigger calculation raises: record/log current behavior, let the current due occurrence proceed, then `transition_to(COMPLETED)` with `schedule_status_reason=TRIGGER_ERROR` rather than remove the registration.

Completion is independent of predicate and execution outcomes. The current due occurrence still passes through predicate and overlap behavior using dispatch-local occurrence timing after the job's public timing has been cleared. A completed job remains in every live registration index until explicit removal or owner cleanup.

`schedule_status_reason` is a typed `ScheduleStatusReason` enum (not an unbounded string) with values `LEGACY_UNKNOWN` and `TRIGGER_ERROR`, or `None` for clean status with no override. Normal finite completion uses no reason, while trigger calculation failure uses `TRIGGER_ERROR`. The enum prevents silent proliferation of ad hoc override strings and ensures consumers can exhaustively match on the closed set. Operator surfaces explain the error-backed completion without adding another public schedule-status value. The DB column stores the enum's string values with a `CHECK (schedule_status_reason IN ('legacy_unknown', 'trigger_error') OR schedule_status_reason IS NULL)` constraint.

### Manual Submission

Add one `SchedulerService.submit_job(job)` method used by `Job.submit()` and the web route. The method:

1. Confirms `job.db_id` maps to the same object in `_jobs_by_id`; otherwise raises `JobRemovedError`.
2. Spawns `run_job_with_guard(job, trigger_mode="manual")` through `SchedulerService.task_bucket`.
3. Returns `None` immediately.

It does not inspect or mutate schedule status, timing, trigger, or predicate. It does not preflight `single` mode or queue capacity. Existing guard behavior and telemetry decide those outcomes.

The HTTP route resolves by registry ID and calls this method. A missing live registration raises the existing domain error translated to HTTP 409. A live registration always returns 202 accepted. CLI and frontend continue calling that endpoint.

`run_job()` must avoid schedule-lag calculations for non-scheduled manual execution. Calculate lag only for automatic dispatches with concrete `fire_at`; manual trigger telemetry remains distinguished by `trigger_mode="manual"`.

### Removal

Rename public APIs and internal intent-bearing helpers:

- `ScheduledJob.cancel()` -> `Job.remove()`
- `Scheduler.cancel_job()` -> `Scheduler.remove_job()`
- `Scheduler.cancel_group()` -> `Scheduler.remove_group()`
- persistence `mark_job_cancelled()` -> `mark_job_removed()`

Use one service removal operation for explicit removal, replacement, and owner cleanup. It removes registry membership first so no new submission can be accepted, marks the job with a private removed flag for stale-handle checks/debugging, removes any heap occurrence, releases the guard, drains queued completion futures, fires per-owner cleanup callbacks, and persists `removed_at` when the removal represents a completed live registration.

Removal callbacks continue cleaning per-app name/group indexes and EntityTime subscriptions. Owner cleanup uses the per-app `Scheduler`'s already-held job list: `Scheduler._remove_all_jobs()` passes its own `_jobs_by_name` values to a `SchedulerService.remove_jobs(jobs: list[Job])` that performs identity-checked per-job removal (heap + registry + guard + persistence) for exactly the given objects. This avoids a global O(n) scan of `_jobs_by_id` and reuses the existing pattern where the `Scheduler` knows its owned jobs and the service executes the removal.

### Persistence And Queries

Add a sequential SQLite migration that renames `scheduled_jobs.cancelled_at` and `listeners.cancelled_at` to `removed_at`. The terminology is a cross-registration correction: both values currently represent registration removal, while execution cancellation remains in execution status. The migration also extends the scheduled-job trigger constraint with `manual` and adds persisted `schedule_status` plus nullable `schedule_status_reason` columns.

Update repository registration upserts, mark-removed methods, active-registration filters, summary queries, migration tests, and schema-freshness artifacts. Preserve existing timestamp values during migration. No `next_run` column is added. The `register_job()` upsert's `ON CONFLICT DO UPDATE SET` clause must explicitly include `schedule_status = excluded.schedule_status, schedule_status_reason = excluded.schedule_status_reason` so that re-registration clears `legacy_unknown` — matching the existing convention where `cancelled_at = NULL` is explicitly listed in `DO UPDATE SET`.

Persist manual-only jobs with explicit trigger metadata. Persist every schedule-status transition (`scheduled`, `waiting`, `completed`, `manual`) and diagnostic reason through the existing command/repository boundary. Add both fields to `JobSummary`; live enrichment overlays the current `Job` state, while persisted values keep DB-only degraded responses truthful after a row has been registered under the new model. Legacy migrated rows carry `schedule_status_reason="legacy_unknown"` until live re-registration establishes exact status; consumers must treat the reason as overriding normal guarantees of the placeholder status. `next_run` and `fire_at` remain live-only and are null in a degraded DB-only response even when status is scheduled; this means timing is temporarily unavailable, not that the schedule is completed. Active operator lists filter using `removed_at IS NULL AND retired_at IS NULL`. These two columns serve distinct lifecycle purposes: `removed_at` marks explicit runtime removal (user action, code removal, `if_exists="replace"` replacement, or registration-rollback after persistence succeeds but a later step fails), while `retired_at` marks startup-time reconciliation (set by `reconcile_registrations()` when a job falls out of `live_job_ids` across a restart, typically after a crash where graceful shutdown never ran). Under FR#21, graceful shutdown removes every owned job via the explicit removal path (setting `removed_at`), so `retired_at` matters only for crash-restart cycles. Both columns must be filtered because either can leave a stale row active. The retention system uses `retired_at` specifically for garbage collection (`WHERE retired_at IS NOT NULL AND retired_at < ?`). Both columns are cleared to `NULL` by the `ON CONFLICT DO UPDATE` upsert on re-registration, matching the existing `cancelled_at = NULL` convention — this is required for `if_exists="replace"` to work correctly, since the replacement's upsert targets the same row as the old job's `removed_at` write. The semantic distinction between the two columns is why they were set (explicit removal vs. reconciliation), not whether the upsert clears them. Legacy rows for jobs that are never re-registered (app removed, job renamed) will keep their `scheduled`/`legacy_unknown` placeholder permanently; this is an accepted limitation of a schema that never purges telemetry rows.

### Operator Surfaces

Update API enrichment in `src/hassette/web/utils.py` to join all live jobs from the registry and include `schedule_status`, `schedule_status_reason`, nullable `next_run`, `fire_at`, and jitter. Normally enriched scheduled jobs expose timing; waiting, completed, and manual jobs expose null timing. On live-enrichment failure, persisted status and reason remain available but timing is explicitly unavailable and therefore null.

The CLI job table adds or incorporates schedule status and renders clear text rather than generic `done` for every null time. The frontend job rows/detail display:

- Scheduled: next relative time.
- Scheduled with null timing because live enrichment is unavailable: “Timing unavailable.”
- `scheduled` with `legacy_unknown` (the only combination the migration produces): “Legacy status unknown” until live re-registration replaces the placeholder status and clears the reason.
- Waiting: “Waiting for entity time.”
- Completed without a reason: “Schedule completed.”
- Completed with `trigger_error`: “Schedule stopped after trigger error.” The error is logged at the time of the trigger calculation failure; no additional DB column is added for the error message.
- Manual: “Manual only.”

Run Now remains available for every live status. Because remote submission now always returns 202 (suppression and queue-drop outcomes are no longer synchronous), the frontend Run Now button must provide post-submission feedback so the operator knows whether the invocation actually ran. After submitting, poll for a new execution record and show a success toast when one appears; if no record appears within a reasonable timeout, show "No execution recorded." Suppressed/dropped invocations never create an execution record (the guard prevents `CommandExecutor.execute()` from being called), so the timeout-based fallback is the detection mechanism for those outcomes. Without this feedback, a click that silently did nothing is a UX regression from the current inline 409 error. Generated TypeScript types come from the updated OpenAPI schema rather than handwritten duplication.

## Implementation Preferences

- Use `guard_await()` for `Scheduler.register()` so forgotten-await diagnostics match existing registration APIs.
- Keep all submitted work in `SchedulerService.task_bucket`; do not expose raw `asyncio.Task` objects.
- Keep overlap policy per `Job` and reuse `ExecutionModeGuard` unchanged.
- Reuse `ExecuteJob`, `CommandExecutor`, `ExecutionRecord`, and existing manual trigger telemetry.
- Use Pydantic models as the OpenAPI source and regenerate frontend types through existing tooling.
- Follow existing Typer/Rich column-formatting conventions in `src/hassette/cli/commands/job.py`.
- Follow existing Tailwind/shadcn patterns; no new visual system is required.
- Make a clean API break without compatibility aliases.

## Replacement Targets

- `src/hassette/scheduler/triggers.py` `NO_OCCURRENCE`: remove; waiting state replaces sentinel scheduling.
- `src/hassette/core/scheduler_service.py` heap-based live lookup and owner removal: replace with registry-based lookup/removal.
- `src/hassette/core/scheduler_service.py` exhaustion removal: replace with completion state transition.
- `src/hassette/web/routes/scheduler.py` one-shot dequeue and `single` preflight: remove; shared submission does not mutate schedules or synchronously expose admission.
- Public `ScheduledJob` and scheduler cancellation APIs: rename to `Job` and removal APIs.
- Persistence `cancelled_at` registration fields and methods: migrate to `removed_at`.
- CLI/frontend null-next-run fallback: replace with explicit schedule-status presentation.

## Migration

Add a new numbered SQL migration following the current migration sequence. Rename `cancelled_at` to `removed_at` on both `scheduled_jobs` and `listeners`, preserving nullability and existing timestamp values. Rebuild the scheduled-jobs constraint to allow `manual`, add non-null `schedule_status` with `CHECK (schedule_status IN ('scheduled', 'waiting', 'completed', 'manual'))` (matching the existing `trigger_type` constraint convention), and add nullable `schedule_status_reason`. This is the first migration in the project's history to rebuild an FK-parent table (`scheduled_jobs` is referenced by `executions.job_id`); the rebuild's `INSERT ... SELECT` must explicitly enumerate and preserve `id`, and AC#6 migration tests must include a `PRAGMA foreign_key_check` (or row-count/id-set diff assertion) verifying `executions.job_id` still resolves for every pre-existing row. Existing rows cannot be assigned a truthful schedule state from persisted data because the old schema did not store heap state. Backfill the required non-null status with `scheduled` but also set reason `legacy_unknown`; that reason explicitly invalidates normal `scheduled` guarantees and all consumers render it as unknown rather than scheduled. Removed historical rows keep the same marker; removal remains orthogonal and those rows are excluded from active lists. Runtime registration updates every live row to its exact current status and clears `legacy_unknown` before app startup completes. Degraded queries during partial startup show “Legacy status unknown” instead of fabricating completion or a pending occurrence. Update all active-registration and summary queries atomically with the migration.

The migration is forward-only in normal operation. Rolling code back after the database migrates would require a reverse schema migration because old code expects `cancelled_at`; this is an accepted clean-break cost.

Runtime public imports and methods change without aliases. Existing app code importing `ScheduledJob` or calling `cancel()`, `cancel_job()`, or `cancel_group()` must migrate to `Job` and removal names.

## Convention Examples

### Guarded awaited registration

**Source:** `src/hassette/scheduler/scheduler.py`

```python
return guard_await(
    self._add_job_and_watch_entity(job, trigger, if_exists=if_exists),
    owner=self.parent,
    source_location=source_location,
    method_name="schedule",
)
```

### Service-owned fire-and-observe dispatch

**Source:** `src/hassette/web/routes/scheduler.py`

```python
scheduler_service.task_bucket.spawn(
    scheduler_service.run_job_with_guard(job, trigger_mode="manual"),
    name="scheduler:manual_trigger",
)
```

### Shared overlap execution path

**Source:** `src/hassette/core/scheduler_service.py`

```python
await run_through_guard(
    guard=job.guard,
    spawn=lambda coro, *, name: self.task_bucket.spawn(coro, name=name),
    pending_done=job.pending_done,
    invoke=lambda: self.run_job(job, trigger_mode=trigger_mode),
    warn=lambda secs: self.warn_stalled_job(job, secs),
    spawn_name="scheduler:mode_invocation",
    threshold=STALL_THRESHOLD_SECONDS,
)
```

### EntityTime registration reconciliation

**Source:** `src/hassette/scheduler/scheduler.py`

```python
current = trigger.resolve(date_utils.now()) or NO_OCCURRENCE
if current != job.next_run:
    await self.scheduler_service.reschedule_job(job, current)
```

### Live operator enrichment

**Source:** `src/hassette/web/utils.py`

```python
live_by_db_id = {job.db_id: job for job in live_jobs if job.db_id is not None}

for js in db_jobs:
    live_job = live_by_db_id.get(js.job_id)
    if live_job is not None:
        guard = live_job.guard
        enriched.append(
            js.model_copy(
                update={
                    "next_run": live_job.next_run.timestamp(),
                    "fire_at": live_job.fire_at.timestamp() if live_job.jitter is not None else None,
                    "jitter": live_job.jitter,
                    "suppressed_count": guard.suppressed,
                    "dropped_count": guard.dropped,
                }
            )
        )
```

## Alternatives Considered

### Generic execution definitions and trigger bindings

Rejected because Hassette already shares the execution layer through `CommandExecutor`, `ExecutionModeGuard`, and `TaskBucket`. New definition/request/run identities, services, and queues would add migration and lifecycle cost without another concrete producer.

### Fake far-future schedule

Rejected because it repeats the sentinel defect in app code, pollutes heap and operator state, and can eventually execute unexpectedly.

### Waiting `run()` plus result propagation

Rejected because jobs are side-effect-oriented, scheduled execution already discards return values, and result/status semantics would move Hassette toward workflow orchestration. `submit()` plus existing telemetry is sufficient.

### Keep completed one-shots non-live

Rejected because manual submission is first class and schedule completion is independent of registration lifetime.

### Keep `cancel()` terminology

Rejected because it conflates registration removal with interruption of active execution. Removal is the public lifecycle action; cancellation remains an execution outcome.

## Test Strategy

### Required Test Types

- Unit: schedule-state transitions, registry lookup, submission validation, removal, queue rejection, schemas, CLI formatting, and frontend mapping/rendering.
- Integration: Scheduler/SchedulerService lifecycle, EntityTime watcher races, overlap modes, persistence/reconciliation, API submission, replacement rollback, and migration behavior.
- System: real scheduler timing and owner cleanup with scheduled, completed, waiting, and manual jobs.
- E2E: manual-only job discovery and Run Now through the frontend against the backend.

### Existing Tests to Adapt

- `tests/unit/test_scheduler_resource.py`: public type/API and per-app indexes.
- `tests/integration/test_scheduler.py`: `Job` construction, registration, args/kwargs, removal, and completion retention.
- `tests/integration/test_scheduler_entity_time.py`: remove sentinel assertions and cover waiting transitions.
- `tests/integration/test_scheduler_mode.py`: removal naming and completed-job guard behavior.
- `tests/unit/core/test_scheduler_service_dequeue.py`: split heap removal from registration removal.
- `tests/unit/core/test_scheduler_service_reschedule.py`: waiting/scheduled transitions.
- `tests/unit/core/test_scheduler_service_trigger.py`: registry lookup, accepted overlap outcomes, and schedule independence.
- `tests/unit/test_scheduler_job_names.py`: register/schedule collision and destructive replacement.
- `tests/system/test_scheduler.py`: removal group naming and manual jobs.
- Migration and telemetry query tests under `tests/unit/` and `tests/integration/database/`: `removed_at` schema and filtering.
- Frontend job-detail, handler-row, endpoint, and generated-type tests under `frontend/src/`: schedule status and submission behavior.
- E2E fixtures/tests under `tests/e2e/`: include a manual-only live job.

### New Test Coverage

- FR#1-FR#3: manual-only registration and unified public type.
- FR#4-FR#10: status transitions, heap exclusion, completion retention, and manual metadata.
- FR#11-FR#17: submission path, predicate bypass, fixed arguments, all execution modes, stale handles, and non-mutating one-shot submission.
- FR#18-FR#21: removal, owner cleanup, replacement failure, and reload reconciliation.
- FR#22-FR#23: operator status rendering and removal persistence migration.
- FR#24: ordinary trigger behavior remains unchanged.

### Tests to Remove

- Tests asserting `NO_OCCURRENCE` or year-9999 heap residency.
- Tests asserting pending one-shots are dequeued by Run Now.
- Tests asserting completed one-shots are not triggerable solely because they left the heap.
- Tests for public cancellation names replaced by removal API coverage.

## Documentation Updates

- `docs/pages/core-concepts/scheduler/index.md`: introduce manual-only registration and `Job`.
- `docs/pages/core-concepts/scheduler/methods.md`: document `register()` and updated return type.
- `docs/pages/core-concepts/scheduler/management.md`: replace cancellation terminology, document `submit()`, removal, statuses, groups, and completed-job lifetime.
- `docs/pages/core-concepts/scheduler/triggers.md`: describe EntityTime waiting without sentinel scheduling.
- `docs/pages/core-concepts/scheduler/execution-modes.md`: explain manual submission uses the same overlap modes and telemetry-only admission outcomes.
- `docs/pages/web-ui/debug-handler.md`: rewrite the 409 paragraph — 409 now means removed/stopped-owner only; suppression/drop outcomes are telemetry-only.
- `docs/pages/migration/scheduler.md`, `docs/pages/migration/checklist.md`: migrate `ScheduledJob`/`cancel()`/`cancel_group()` references.
- `docs/pages/core-concepts/internals/service-details.md`: update scheduler service descriptions.
- All executable snippet `.py` files under `docs/pages/core-concepts/scheduler/snippets/` and `docs/pages/recipes/snippets/`: migrate imports and API calls (`ScheduledJob` -> `Job`, `cancel*` -> `remove*`). These are outside `pyrightconfig.json`'s `include` list and have no test coverage, so silent breakage has no CI signal.
- `src/hassette/web/CLAUDE.md`: update `SchedulerDep` description — `get_all_jobs()` reads the service registry (not the heap), and `mark_job_cancelled()` is renamed to `mark_job_removed()`.
- CLI reference/help and generated API documentation: expose statuses and removal language.
- Relevant generated doc screenshots under `docs/_static/`: regenerate if handlers/job views visibly change.
- Do not edit `CHANGELOG.md`; release-please will generate entries from commits.
- Ship as `feat!:` with a `BREAKING CHANGE:` footer enumerating the renamed imports/methods, per the project's changelog-quality convention. The footer must also note that `next_run == null` in API responses no longer implies "job finished" — consumers must read `schedule_status` to distinguish waiting, completed, manual, and timing-temporarily-unavailable states.

## Impact

### Changed Files

- Modify `src/hassette/scheduler/classes.py`: rename `ScheduledJob`, add schedule status, optional timing, submission, and removal handle methods.
- Modify `src/hassette/scheduler/scheduler.py`: add registration, common job construction, removal APIs, completion-compatible indexes, and EntityTime transitions.
- Modify `src/hassette/core/scheduler_service.py`: add live registry, status transitions, shared submission, registry-based cleanup, and completion retention.
- Modify `src/hassette/scheduler/triggers.py`: remove `NO_OCCURRENCE` while retaining existing trigger protocol behavior.
- Modify `src/hassette/commands.py`, `src/hassette/types/types.py` (`SchedulerServiceProtocol.mark_job_cancelled` → `mark_job_removed`), and scheduler-related type protocols: rename runtime job types without changing command semantics.
- Modify `src/hassette/core/registration.py`, telemetry repository/query modules, and add a migration under `src/hassette/migrations_sql/`: manual metadata and `removed_at`.
- Modify `src/hassette/bus/bus.py`, `src/hassette/bus/options.py` (docstring), `src/hassette/core/bus_service.py`, and `src/hassette/core/command_executor.py`: mechanical `cancelled_at` → `removed_at` rename for the listener-side column (same migration renames both tables).
- Modify `src/hassette/exceptions.py`: add `JobRemovedError` (FR#16).
- Modify `src/hassette/schemas/job_models.py`, `src/hassette/web/utils.py`, `src/hassette/web/routes/scheduler.py`, and `src/hassette/web/models.py`: statuses, registry enrichment, and shared submission semantics.
- Modify `src/hassette/cli/commands/job.py`: truthful status and next-run rendering.
- Modify frontend endpoint, generated type, row mapping, job detail, and related test files under `frontend/src/`: four statuses and live submission. Specifically, `UnifiedRow` in `frontend/src/utils/handler-rows.ts` must add a `schedule_status` field and the sort comparator must use it as a secondary sort key when `next_run_ts` is null, so the four null-timing states (waiting, completed, manual, degraded-scheduled) sort into distinct, predictable positions rather than lumping into one bucket.
- Modify scheduler, telemetry, migration, web, CLI, frontend, system, and E2E tests identified above.
- Modify scheduler documentation pages, affected generated screenshots, and `src/hassette/web/CLAUDE.md` (`SchedulerDep` description).

<!-- Gap check [2026-07-31]: 8 gaps included —
  sync.py + codegen (scheduler/sync.py, codegen/sync_facade/generic.py) → T08
  scheduler/__init__.py exports → T01
  core/state_proxy.py ScheduledJob import → T01
  web/routes/telemetry.py enrich call → T06
  test_utils/ factories (factories.py, web_job_helpers.py, web_mocks.py) → T03/T06
  tooling scripts (gen_ref_pages, check_bare_symbols, check_test_factories, check_registration_signatures, seed_db.py) → T08
  bus/sync.py docstring → T08
  additional test files beyond "Existing Tests to Adapt" → T03/T04/T05/T06/T07
-->

### Behavioral Invariants

- Every awaited registration returns with a valid persisted ID.
- Stable names remain required and unique per scheduler owner.
- Automatic dispatch evaluates predicates; manual submission bypasses them.
- Existing execution modes, timeouts, error handlers, execution telemetry, and sync adaptation retain their semantics.
- Recurring jobs enqueue their next occurrence before current execution so overlap remains possible.
- EntityTime registration retains its watcher and post-registration reconciliation race protection.
- Manual submission never mutates automatic schedule state.
- Removed registration history and execution history remain queryable.
- `TriggerProtocol.first_run_time()` return type widens from `ZonedDateTime` to `ZonedDateTime | WaitingSentinel`, and `next_run_time()` widens from `ZonedDateTime | None` to `ZonedDateTime | None | WaitingSentinel`, to accommodate `EntityTime`'s WAITING return. Existing triggers continue returning their current types and existing `if_past` behavior remains unchanged.

### Blast Radius

The change touches the public scheduler API, scheduler lifecycle internals, telemetry schema and queries, OpenAPI contracts, CLI output, frontend job presentation, documentation, and tests. Existing apps using scheduler cancellation names or importing `ScheduledJob` require source changes. The Bus and state-event systems are affected only as existing dependencies of EntityTime and are not redesigned.

## Open Questions

None.
