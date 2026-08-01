---
topic: "Registered scheduler jobs independent of heap residency"
date: 2026-07-30
status: Draft
issue: 1489
---

# Research Brief: Registered Jobs Without Active Schedules

## Executive Summary

Issue 1489 exposes a real scheduler modeling gap: Hassette cannot represent a registered job that currently has no next occurrence. `EntityTime` works around this by returning a year-9999 sentinel, keeping the job in the due-time heap even though it is not meaningfully scheduled.

The proportional fix is scheduler-local:

- Rename `ScheduledJob` to `Job` and keep it as the single scheduler-owned executable unit for scheduled and manual-only registrations.
- Add a `SchedulerService` registry containing every live job.
- Make the due-time heap contain only jobs with an active next occurrence.
- Represent waiting explicitly rather than with a fabricated timestamp.
- Resolve inspection and manual submission through the registry instead of heap membership.
- Preserve `ExecuteJob`, `CommandExecutor`, `ExecutionModeGuard`, and `TaskBucket` as the execution path.
- Distinguish schedule completion, job removal, and execution cancellation in behavior and public terminology.
- Add `scheduler.register(...)` for manual-only jobs and `job.submit() -> None` for fire-and-observe invocation.

This solves the demonstrated problem without introducing a generic execution service, reusable executable definitions, producer adapters, another request queue, or new public terminology. Bus and Scheduler already share execution machinery where it pays; no Bus refactor is justified by issue 1489.

## Current Architecture

### Registration

`Scheduler.schedule()` creates a `ScheduledJob`, records it in per-app indexes, and delegates service registration to `SchedulerService.add_job()`. The service persists a `ScheduledJobRegistration`, assigns `job.db_id`, and inserts the job into `_ScheduledJobQueue`.

Relevant runtime indexes already exist in the per-app `Scheduler`:

- `_jobs_by_name`
- `_jobs_by_group`
- `_entity_time_subs`

These support app-facing lookup, group operations, and `EntityTime` watcher ownership. They do not provide service-level lookup by database job ID.

### Scheduling

`_ScheduledJobQueue` is a due-time priority queue. `SchedulerService.serve()` removes due entries and dispatches them. Recurring jobs calculate and enqueue their next occurrence before the current occurrence executes.

The heap currently also acts as the service-level source for global live-job enrichment and Run Now lookup. This makes heap residency stand in for runtime job existence.

### Execution

The actual execution boundary is already shared and mature:

- `ExecuteJob` carries scheduler-specific execution context.
- `CommandExecutor` owns execution IDs, timeout/error classification, log correlation, telemetry, completion events, and error-hook routing.
- `ExecutionModeGuard` owns per-job overlap behavior.
- `TaskBucket` and `SyncExecutor` own async task lifecycle and sync callable adaptation.

No additional execution kernel is required.

### EntityTime

An `EntityTime` trigger may have no valid next occurrence when its source entity is unavailable, unknown, or otherwise unusable. Because registration currently requires a heap time, `NO_OCCURRENCE` parks the job at year 9999.

`EntityTime` also has important reactivation behavior that must remain intact:

- A framework Bus listener watches source entity changes.
- A post-registration state re-read closes the race between the initial read and watcher installation.
- A valid changed value reschedules the job.

Removing heap parking must not weaken this watcher and reconciliation behavior.

### Run Now

The Run Now route currently resolves a job from the scheduler heap. That behavior intentionally enforces some existing semantics:

- Already-fired one-shots are unavailable.
- Temporarily popped one-shots are unavailable.
- Jobs owned by stopped apps are unavailable.
- Pending one-shots are dequeued before manual execution so they do not fire again later.

Moving lookup to a registry intentionally revises these rules: manual submission becomes independent of automatic scheduling, so pending and completed one-shots remain submit-capable. Stopped-owner and removed-job rejection remain.

## The Architectural Gap

The due-time heap currently answers two different questions:

1. Which job occurrence should fire next?
2. Which jobs currently exist and can be inspected or manually invoked?

Only the first question belongs to a priority queue. A live job can exist without a next occurrence, and a recurring job can temporarily be absent from the heap while dispatching.

The missing abstraction is therefore not a framework-wide executable definition. It is a scheduler-service registry independent of the due-time heap.

## Recommended Runtime Model

```text
SchedulerService
  live job registry
    - every runtime-addressable Job
    - lookup by persisted job ID
    - owner cleanup and registration removal

  due-time heap
    - only jobs with an active next occurrence
    - ordering and wake-up behavior only

  existing execution path
    Job -> ExecuteJob -> CommandExecutor -> ExecutionRecord
```

### Live Job Registry

The registry should live in `SchedulerService`, which already owns:

- Heap mutation
- Persistence registration
- Manual triggering
- Global live-job enrichment
- Owner-wide cleanup
- Dispatch and registration removal

The likely minimal shape is a dictionary keyed by persisted job ID. `db_id` is available after awaited registration and is already the identifier used by web and telemetry surfaces.

The registry is the service-level authority for whether a job is live and runtime-addressable. It is not historical storage; removed jobs remain visible through database telemetry rather than the live registry.

### Due-Time Heap

The heap should contain only jobs that have a concrete next occurrence. It should not be queried to determine whether a job exists.

Heap operations remain responsible for:

- Ordering active occurrences
- Waking the scheduler when the earliest occurrence changes
- Removing or replacing an active occurrence
- Supplying due jobs to dispatch

### Schedule Availability

A job's automatic schedule is independent of whether its registration remains live. Keep the core timing invariant narrow: jobs with an active occurrence have concrete `next_run` and `fire_at` values and belong to the heap; jobs without an occurrence remain outside it. Do not make core timing broadly nullable unless implementation analysis proves that a small schedule-state representation cannot preserve existing `Job` and queue invariants. A general-purpose runtime state machine is unnecessary.

For `EntityTime`, temporary inactivity means:

- The job remains in the live registry.
- The job is absent from the heap.
- Its entity watcher remains installed.
- Its post-registration reconciliation remains intact.
- It can return to the heap when the entity yields a valid time.
- It remains visible to API, CLI, and UI consumers.
- It remains submit-capable through the shared manual submission path.

Waiting is not schedule completion. When a one-shot or other finite trigger has no future automatic occurrence, its schedule is completed but the job remains live and manually invocable. A manual-only job never has an automatic occurrence. Only explicit job removal, replacement, or owner shutdown removes the registration from the live registry.

## Product Semantics And Vocabulary

Hassette should distinguish three independent concepts that the current `cancel()` terminology conflates.

### Job Registration

A job registration is either live or removed.

- **Live**: the job remains in `_jobs_by_id`, can be inspected, and can be invoked manually.
- **Removed**: the job is absent from `_jobs_by_id`; neither automatic nor manual invocation is available. Historical registration and execution telemetry remain persisted.

The public operation should be named `remove`, not `cancel`:

```python
job.remove()
scheduler.remove_job(job)
scheduler.remove_group("morning")
```

Removal also cleans up pending automatic occurrences, trigger watchers, active execution, and queued execution according to existing cleanup behavior. A clean public API break is acceptable; compatibility aliases are not required unless a concrete external compatibility need is identified.

### Automatic Schedule

The automatic schedule has a separate lifecycle while the job remains live:

- **Scheduled**: a concrete future automatic occurrence exists.
- **Waiting**: no occurrence currently exists, but the trigger may produce one later, as with an unavailable `EntityTime` source.
- **Completed**: the trigger cannot produce another automatic occurrence, as after a one-shot fires.
- **Manual**: no automatic trigger was configured.

`schedule_status` is public on `Job` and in operator-facing job summaries, using the machine-readable values `scheduled`, `waiting`, `completed`, and `manual`. Waiting, completed, and manual jobs remain submit-capable. A manual submission does not consume, move, or otherwise mutate a pending automatic occurrence. A pending one-shot submitted before its scheduled time therefore still fires automatically at that time.

After an automatic occurrence, an ordinary trigger's `next_run_time()` returning `None` means its automatic schedule is completed. `TriggerProtocol.first_run_time()` remains non-optional, so registration-time completion for ordinary triggers is out of scope. `EntityTime` waiting remains a specialized integration because it already owns Home Assistant state reading, a framework Bus watcher, and registration-time reconciliation. `TriggerProtocol` is not generalized until another recoverable trigger needs to express waiting. Existing built-in timing behavior remains unchanged, including `Once`/`run_once()` handling of past values through its existing `if_past` policy.

### Manual-Only Registration

Manual-only jobs are a demonstrated product requirement, not speculative extensibility:

```python
job = await scheduler.register(
    self.rebuild_scene,
    name="rebuild_scene",
    mode="single",
    args=(),
    kwargs={},
)

job.submit()
```

`scheduler.register(...)` returns the same `Job` type as `schedule(...)` and its convenience methods. It accepts the existing registration-scoped execution policy, including name, group, timeout, mode, error handler, args, kwargs, and `if_exists`. It does not accept `where=` because predicates govern automatic occurrences and manual submission bypasses them.

The distinct `register` verb is intentional: `schedule(...)` promises an automatic trigger, while `register(...)` creates a live manual-only job. Reusing `schedule(..., trigger=None)` would obscure that product distinction.

Manual-only jobs persist without a fabricated trigger. `schedule_status="manual"` is the authoritative operator signal. The implementation design must choose a truthful encoding for existing trigger metadata fields, such as an explicit manual trigger type with empty or descriptive label/detail values, rather than pretending a time trigger exists.

`job.submit()` is synchronous, returns `None`, and submits one invocation through the existing scheduler `TaskBucket`, `ExecutionModeGuard`, `ExecuteJob`, and `CommandExecutor` path with manual trigger telemetry. It is deliberately fire-and-observe:

- Callable return values remain discarded, as they are for scheduled execution.
- Handler errors, timeouts, and execution cancellation use existing telemetry and error handlers.
- `single` suppression and a full `queued` guard produce no synchronous result; existing suppression/drop telemetry remains authoritative.
- `restart` and `parallel` retain their existing guard behavior.
- A removed handle raises a specific `JobRemovedError` immediately.
- `submit()` accepts no per-invocation args or kwargs. Registered args and kwargs are used for every invocation.
- There is no waiting `run()` API, invocation handle, result object, or execution status model.

Manual submission through Python, API, CLI, and UI follows the same path and bypasses the job predicate, matching the current Run Now behavior. There is no `force=` or `skip_predicate=` option.

Remote submission of any live job returns accepted even if `single` later suppresses it or a full `queued` guard drops it; those outcomes remain telemetry-only, matching `job.submit()`. `409` is reserved for a persisted job whose live registration has been removed or whose owner is unavailable. This intentionally removes the current route's preflight `single` conflict behavior so Python and remote submission share one contract.

### Execution

Cancellation remains the correct term for interrupted running work. Execution-mode restart, job removal, or owner shutdown may cancel an active execution and produce cancelled execution telemetry.

This vocabulary avoids implying that removing a registration deletes its telemetry history, while reserving cancellation for actual task interruption.

### Existing Per-App Indexes

The service registry does not replace `_jobs_by_name`, `_jobs_by_group`, or `_entity_time_subs`.

- Per-app indexes continue to support app-author operations and watcher ownership.
- Inactive jobs remain in `_jobs_by_name` so `Scheduler.get_job_db_ids()` and app startup/reload reconciliation continue to treat them as live registrations.
- The service registry supports global ID lookup and service lifecycle operations.
- The heap represents active timing only.
- The database represents persisted registration and execution history.

The design must specify how mutations keep these structures coherent and how failures roll back partial registration.

## Why Not A Generic Execution Architecture

The initial research considered four conceptual entities: executable definition, trigger binding, execution request, and execution run. Those distinctions are useful when analyzing larger task systems, but Hassette already has proportional equivalents:

| Conceptual role | Current Hassette object |
|---|---|
| Registered scheduler job | `Job` (currently `ScheduledJob`) |
| Source-specific execution request | `ExecuteJob` |
| Concrete run and telemetry outcome | `ExecutionRecord` |
| Execution engine | `CommandExecutor` |

Splitting these roles into new first-class services, tables, APIs, and identities would not solve an additional demonstrated requirement. It would instead require broad migration across persistence, telemetry, web APIs, CLI output, frontend models, lifecycle ownership, and stable registration naming.

The conceptual model may be revisited if Hassette later gains a concrete need such as:

- One callable intentionally shared by several trigger registrations
- Manual execution of event-dependent Bus handlers
- A third trigger-producing subsystem
- A demonstrated behavioral drift that existing shared execution machinery cannot prevent

Until then, the renamed `Job` plus the current execution objects should remain the implementation model.

## Bus And Scheduler Scope

No Bus changes are recommended for issue 1489.

Bus and Scheduler already converge on:

- `CommandExecutor`
- `ExecutionModeGuard`
- `TaskBucket` and `SyncExecutor`
- Unified execution telemetry and completion events

Their remaining differences mostly reflect real source semantics. Bus owns topic routing, event predicates, duration holds, debounce, throttle, priority, and intake backpressure. Scheduler owns next-occurrence calculation, heap ordering, recurrence, jitter, groups, schedule completion, manual-only registration, and `EntityTime` watchers.

Unifying registrations or adding generic producer adapters would introduce abstraction without deleting these domain-specific structures.

## Manual Submission Semantics

Registry lookup makes more jobs addressable than heap lookup. The design must implement the product distinction between a live job and its automatic schedule rather than inheriting behavior accidentally from heap residency.

Required semantics:

- Waiting jobs are submit-capable.
- Recurring jobs temporarily absent from the heap while dispatching are resolved from the registry and pass through their existing `ExecutionModeGuard`.
- Pending one-shots retain their future automatic occurrence after manual invocation.
- Completed one-shots remain in the live registry and are submit-capable.
- Manual-only jobs are submit-capable without any heap entry.
- Explicitly removed jobs and jobs owned by stopped apps are unavailable.
- Existing mode semantics remain per job; no definition-scoped queue or fairness policy is introduced.
- Manual submission bypasses predicates, consistently across Python, API, CLI, and UI.

Preserve `409` for a persisted job that is known but whose live registration has been removed or whose owner is unavailable. Schedule completion and overlap admission outcomes are not conflicts and must not prevent or synchronously reject submission.

## Data And Operator Surfaces

No execution telemetry redesign is required initially.

- `ScheduledJobRegistration` remains the persisted registration.
- `ExecutionRecord.job_id` continues to identify scheduler executions.
- Existing job names remain stable, owner-scoped registration identities.
- API, CLI, and frontend continue to use the noun “job.”
- The runtime handle is renamed from `ScheduledJob` to `Job`; no subtype hierarchy is added.

The main representation change is that a live job may have no next occurrence. The operator-facing `next_run` model is already nullable and the database does not persist `next_run`, so no database migration is needed for this value. Mappers, CLI output, and frontend rendering should combine existing nullability with public `schedule_status` to distinguish waiting, completed, and manual jobs. No fabricated far-future timestamp should remain.

The public lifecycle API changes from `cancel()` to `remove()`. The persistence design must decide whether to migrate `cancelled_at` to `removed_at` or translate the existing column internally; operator-facing language must use removal for registration lifecycle and cancellation only for interrupted executions.

## Concurrency And Consistency

Adding a registry introduces another runtime structure, but it does not justify a new queue or execution service.

The design should map every mutation path involving registry, heap, per-app indexes, and `EntityTime` watchers:

- Initial registration
- Persistence failure
- Heap insertion or replacement
- Temporary deactivation
- `EntityTime` reactivation
- Manual submission
- Recurring dispatch and reschedule
- Schedule completion
- Explicit job removal
- `if_exists="replace"`
- Owner shutdown and app reload

Prefer event-loop serialization where operations contain no observable suspension point. If compound mutations span `await` boundaries and can expose partial state, use the smallest synchronization mechanism justified by the actual race. Do not introduce per-job locks or a general scheduler state machine without a failing concurrency case.

One service method should own registration removal from the registry, heap, per-app indexes, and watcher structures. Schedule completion removes only automatic scheduling state and must not flow through registration removal.

## Prior Art And Proportional Lessons

### APScheduler

APScheduler distinguishes reusable tasks, schedules, execution requests, and executors. The relevant lesson for Hassette is narrow: registered work and active schedule occurrences are different things. Hassette does not need to adopt APScheduler's full object model to apply that distinction to `ScheduledJob` and heap membership.

### Home Assistant

Home Assistant separates automation registration from whether a trigger currently produces an occurrence and applies explicit run modes. Hassette already has equivalent overlap machinery. The useful lesson is to retain a registered automation/job independently of transient source readiness.

### Kubernetes Workqueues And Actor Mailboxes

These systems demonstrate explicit queue bounds, fairness, deduplication, and lifecycle-aware draining. Hassette should not import those mechanisms here: the scheduler heap, Bus intake controls, `ExecutionModeGuard`, and `TaskBucket` already cover distinct timing and execution concerns. Another request queue would create layered buffering rather than simplify it.

### Celery And Temporal

These systems reinforce that registration, request, and run identity can be distinct in distributed or durable execution. Their brokers, redelivery, retries, durable histories, and replay guarantees are outside Hassette's in-process scope. They are boundary examples, not target architectures.

## Anti-Patterns And Footguns

### Heap As Registry

Do not infer runtime existence or manual invocability from due-time heap membership. Heap membership should mean only that the job has an active next occurrence.

### Sentinel Scheduling

Do not encode inactivity as a fabricated timestamp. It leaks into ordering, serialization, UI, and timing assumptions and obscures the actual state.

### Duplicate Authorities

Do not add a registry without defining ownership and synchronization with per-app indexes, heap entries, watchers, and persistence. Each structure should answer a distinct question.

### Silent Manual-Submission Changes

Do not replace heap lookup with registry lookup without implementing the deliberate semantic change: manual invocation is independent of automatic scheduling, including for pending and completed one-shots. Stopped-owner and overlap semantics remain explicit.

### New Execution Queue

Do not place a generic request queue between source dispatch and `ExecutionModeGuard`. Existing Bus backpressure, scheduler timing, overlap queues, and task tracking already have distinct responsibilities.

### Generic Public Vocabulary

Do not expose “definition,” “binding,” or “executable” in APIs, CLI, or UI without a demonstrated reusable-definition feature. “Job,” “listener,” and “execution” remain accurate for current user-facing concepts.

### Workflow Result Semantics

Do not add a waiting `run()` method, callable result propagation, public invocation handles, or Prefect-like execution result/status objects. Jobs are side-effect-oriented and outcomes remain observable through existing telemetry and error handlers.

### Premature State Machine

Do not introduce one large job-state enum spanning registration, scheduling, and execution. These are separate axes. Use the smallest scheduling representation that distinguishes scheduled, waiting, and completed while registry membership represents live versus removed.

### Lost EntityTime Updates

Do not remove heap parking while weakening the state-change watcher or post-registration reconciliation read. A source change during registration must still be observed.

### Partial Registration

Do not expose a job through some indexes but not others after a failed persistence, watcher, or heap operation. Registration and replacement paths need explicit rollback behavior.

## Recommended Scope

### Implement Now

1. Add a service-level live job registry.
2. Make heap membership represent only an active next occurrence.
3. Replace `NO_OCCURRENCE` with truthful waiting state outside the heap.
4. Preserve `EntityTime` watcher and reconciliation behavior.
5. Add `scheduler.register(...)`, rename `ScheduledJob` to `Job`, and add fire-and-observe `job.submit()`.
6. Resolve global live inspection and manual submission from the registry.
7. Rename the public lifecycle API from cancellation to removal and reserve cancellation for interrupted executions.
8. Define registration removal and rollback across registry, heap, per-app indexes, and watchers.
9. Expose `schedule_status` and make next-run presentation truthful for waiting, completed, and manual jobs.
10. Preserve existing execution, overlap, lifecycle, and telemetry machinery.

### Defer

- Generic `ExecutionCore` service
- Reusable executable definitions
- Generic trigger bindings or producer adapters
- Generic manual execution of Bus handlers
- Public executable/handler registration API
- Waiting execution APIs, callable result propagation, invocation handles, and execution result objects
- Persisted request entities
- New request queues and cross-binding fairness
- Retry or durable-delivery semantics
- Bus refactoring unrelated to a demonstrated defect

## Settled Product Requirements

- Live runtime existence is authoritative independently of due-time heap membership; the implementation direction is a `SchedulerService` registry keyed by persisted job ID.
- Live registrations remain submit-capable whether their schedule is scheduled, waiting, completed, or manual.
- Manual submission never changes automatic schedule state or consumes a pending occurrence.
- The final automatic occurrence completes the schedule when consumed, independent of predicate, handler, overlap, timeout, or error outcome.
- Ordinary trigger `None` means completed; `EntityTime` waiting remains specialized.
- `scheduler.register(...)` creates a manual-only job without `where=`.
- `job.submit() -> None` is fire-and-observe, uses registered arguments only, bypasses predicates, and relies on existing telemetry for all execution outcomes.
- Submitting a removed handle raises `JobRemovedError`.
- `job.remove()`, `scheduler.remove_job()`, and `scheduler.remove_group()` remove registrations, automatic occurrences, watchers, active execution, and queued execution while retaining historical telemetry.
- `if_exists="replace"` remains destructive remove-then-register; failure leaves no old registration and must not leave a partial new one.
- `Job.schedule_status` and operator summaries expose `scheduled`, `waiting`, `completed`, or `manual`.
- No waiting invocation API, execution result object, new queue, Bus refactor, or generic execution service is introduced.

## Open Implementation Design Questions

The implementation design should answer these in order:

1. **Schedule representation**: What small internal model represents scheduled, waiting, completed, and manual while preserving concrete timing invariants for heap entries?
2. **Registry transitions**: At exactly which registration, removal, replacement, and owner-lifecycle transitions is `_jobs_by_id` mutated?
3. **Mutation ownership**: Which service methods coordinate registry, heap, per-app indexes, groups, guards, and `EntityTime` watchers?
4. **Concurrency**: Which mutation paths cross `await` boundaries, and is any additional lock required to prevent observable partial state?
5. **Rollback**: How do initial registration and destructive replacement clean up persistence, watcher, registry, index, and heap failures?
6. **Manual submission path**: How should the existing web route, new Python `submit()`, CLI, and UI share one service method without duplicating mode or removed-handle checks?
7. **Removal exception**: Where should `JobRemovedError` live, and how does a `Job` determine removal without creating another source of truth?
8. **Persistence vocabulary**: Should `cancelled_at` migrate to `removed_at`, or should persistence retain the column with an internal compatibility translation?
9. **Operator mapping**: Which API, CLI, frontend, documentation, and test assumptions need updates for `Job`, `schedule_status`, nullable `next_run`, and removal language?
10. **Migration scope**: Which public import, schema, and database compatibility breaks are intentional for this clean API change?

## Recommendation

Proceed with a scheduler-focused design that separates live job registration from active due-time scheduling.

Treat issue 1489 as a scheduler state and lookup correction, not the start of a generic execution platform. Preserve the existing execution stack and public concepts. Revisit broader execution abstraction only when another concrete feature requires it.

## Sources

### Local Code And Design

- `src/hassette/scheduler/scheduler.py`
- `src/hassette/scheduler/classes.py`
- `src/hassette/scheduler/triggers.py`
- `src/hassette/core/scheduler_service.py`
- `src/hassette/commands.py`
- `src/hassette/core/command_executor.py`
- `src/hassette/core/execution_record.py`
- `src/hassette/execution_mode.py`
- `src/hassette/web/routes/scheduler.py`
- `src/hassette/migrations_sql/001.sql`
- `src/hassette/migrations_sql/009.sql`
- `design/specs/002-run-now-button/design.md`
- `design/specs/073-execution-overlap-modes/design.md`
- `design/specs/074-scheduler-overlap-modes/design.md`
- `design/research/2026-04-06-stable-identity-upsert/research.md`
- `design/research/2026-05-28-handler-listener-identity/research.md`

### External References

- APScheduler user guide: https://github.com/agronholm/apscheduler/blob/master/docs/userguide.rst
- Home Assistant automation triggers: https://www.home-assistant.io/docs/automation/trigger/
- Home Assistant automation modes: https://www.home-assistant.io/docs/automation/modes/
- Kubernetes client-go workqueue: https://pkg.go.dev/k8s.io/client-go/util/workqueue
- Akka mailboxes: https://doc.akka.io/libraries/akka-core/current/typed/mailboxes.html
- Celery calling tasks: https://docs.celeryq.dev/en/stable/userguide/calling.html
- Temporal workflows: https://docs.temporal.io/workflows
