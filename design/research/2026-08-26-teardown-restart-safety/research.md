# Research Brief: Prevent Restart After Unconfirmed Resource Teardown

> **Date:** 2026-08-26
> **Status:** Draft
> **Flexibility:** Exploring
> **Depth:** Deep
> **Proposal:** Define explicit teardown outcomes and prevent any new in-process lifecycle generation after teardown fails to prove quiescence.
> **Motivation:** A restart can currently initialize the same `Resource` or `Service` after child shutdown, task cancellation, or force-terminal cleanup failed to prove that the prior incarnation ended.
> **Constraints:** Python 3.11+; preserve bounded shutdown; examine the full Resource/Service/App lifecycle; breaking lifecycle changes are acceptable when they materially improve correctness.
> **Non-goals:** Implementing the change in this research pass; preserving unsafe restart behavior for compatibility.

**Initiated by:** Issue [#1696, “Prevent restart after unconfirmed resource teardown”](https://github.com/NodeJSmith/hassette/issues/1696), with a request to compare the minimum safety fix against broader lifecycle redesign, process-only recovery, and fresh-instance replacement.

## Bottom line

**Recommendation — Supported:** Add an explicit, immutable teardown report; make confirmed quiescence a hard admission requirement at both `restart()` and `initialize()`; and treat teardown refusal as a process-fatal supervision outcome. Keep same-instance restart for the normal, confirmed-clean path. Do not use fresh framework-service instances as the fallback: a new Python object does not isolate it from old tasks, subscriptions, threads, or shared capabilities that remain alive.

The minimum invariant should be:

> Lifecycle generation N+1 may not begin until generation N has a teardown report proving that its hooks completed, owned async work ended, its `Service.serve()` task ended, and all children reported confirmed quiescence. A timeout, exception, force-terminal patch, or still-running owned task is evidence of **unconfirmed teardown**, not successful shutdown.

This is stricter than checking `status == STOPPED`, `shutdown_completed`, or whether one task happens to be done. Those fields currently describe lifecycle bookkeeping, not proof that all prior work and registrations are gone (`base.py:332-353,379-412`; `mixins.py:130-140`).

## Context

### What prompted this

**Direct:** Issue #1696 identifies two required regressions: a parent whose child shutdown times out, and a `Service` whose `serve()` task does not cooperate with cancellation. In both cases, the old incarnation must become ineligible for in-process restart. The issue explicitly says force-terminal cleanup may remain an exit-oriented fallback but cannot authorize restart.

**Direct:** The existing architecture intentionally supports same-instance service restart. `ServiceWatcher` receives `FAILED`, applies exception routing and a sliding-window budget, then calls the module-level `restart(service)` after backoff or cooldown (`service_watcher.py:322-445`). `restart()` always executes `await resource.shutdown(); await resource.initialize()` (`operations.py:63-67`).

### Current lifecycle and data flow

**Direct:** Lifecycle state is held on each object by `LifecycleMixin`: `_status`, `_previous_status`, readiness/shutdown events, `_init_task`, and the boolean `shutdown_completed` (`mixins.py:111-140`). `Resource` adds `initializing`, `shutting_down`, children, and a per-resource `TaskBucket` (`base.py:91-183`). `Service` adds `_serve_task` (`service.py:58`).

**Direct:** Status transitions are emitted as `ServiceStatusPayload` and projected through `RuntimeQueryService` to WebSocket clients (`events/hassette.py:29-46`; `runtime_query_service.py:171-185`). The payload exposes status, exception, retry time, and readiness, but no teardown outcome or restart-eligibility field. The system snapshot has the same gap (`domain_models.py:46-56,131-154`; `runtime_query_service.py:297-305`).

**Direct:** The frontend has exhaustive maps for every `ResourceStatus`; adding a new status requires updating generated API types and both status maps (`frontend/src/utils/status.ts:23-40,120-138,172-193`). Additive teardown metadata would have a smaller frontend cascade than a new combined lifecycle status.

### Exact unsafe paths

#### 1. Child shutdown timeout followed by restart

**Direct:**

1. `restart(resource)` calls `resource.shutdown()` (`operations.py:63-67`).
2. `_finalize_shutdown()` calls `_shutdown_children()` and receives `False` when a child wave times out (`base.py:355-390`).
3. The timeout handler calls `child._force_terminal()`. `_force_terminal()` cancels without awaiting, skips shutdown hooks, writes `_status = STOPPED`, and sets `shutdown_completed = True`. Its own comment accepts stale subscriptions because the path is expected to be followed by process exit (`base.py:332-353`).
4. `_finalize_shutdown()` discards the failed `children_clean` result for admission purposes, sets the parent’s `shutdown_completed = True`, and generally emits `STOPPED` (`base.py:390-412`).
5. `restart()` unconditionally calls `initialize()`, which immediately clears `shutdown_completed` and `shutdown_event` before any admission check (`base.py:431-445`; `service.py:94-115`).

The existing timeout tests encode the bookkeeping behavior: timed-out resources become `STOPPED` with `shutdown_completed=True` (`test_shutdown.py:201-222`; `test_force_terminal.py:81-167`). They do not test restart refusal.

#### 2. Noncooperative `Service.serve()` task

**Direct:** `Service.shutdown()` cancels `_serve_task` and awaits it with `asyncio.wait_for()` (`service.py:135-164`). If it catches `TimeoutError`, it only logs and continues into hooks and `_finalize_shutdown()`. `TaskBucket.cancel_all()` also only logs pending tasks as “refused to die” and returns no result to the lifecycle (`task_bucket.py:316-350`). The service can therefore be marked shutdown-complete without a positive assertion that the serve task and all owned tasks ended.

**Direct external evidence:** Python documents cancellation as cooperative and says `wait_for()` waits until the target is actually cancelled, so total wait may exceed the configured timeout. It also warns that `asyncio.timeout()` and task groups may misbehave when a coroutine swallows `CancelledError`. Therefore the present code has two failure modes: a partially resistant task may survive long enough for shutdown bookkeeping to proceed, while a fully resistant task may defeat the intended wall-clock bound entirely. `asyncio.wait(tasks, timeout=...)` is the relevant non-blocking observation primitive because it returns pending tasks without waiting for them to acknowledge another cancellation.

#### 3. Other admission bypasses

**Direct:** Gating only `operations.restart()` would be incomplete. `start(resource)` resets `shutdown_completed` and spawns `initialize()` (`lifecycle.py:90-100`), while both `Resource.initialize()` and `Service.initialize()` reset shutdown state themselves. A caller can therefore bypass a restart-only check.

**Direct:** Duplicate shutdown calls currently return immediately when `shutting_down` is true (`base.py:482-499`; `service.py:137-165`). A concurrent restart caller can interpret that early return as completed shutdown and continue unless shutdown callers coalesce around one result. `ServiceWatcher._restarting` protects duplicate watcher `FAILED` events, but it is not a resource-wide lifecycle lock and does not protect direct calls or every cooldown path (`service_watcher.py:370-396`).

#### 4. App replacement has the same class of hole

**Direct:** `AppLifecycleService.shutdown_instance()` applies an outer timeout and catches shutdown failure, but returns no success/failure result (`app_lifecycle_service.py:290-329`). `_stop_instance_unlocked()` unregisters the old instance before awaiting shutdown and catches any failure (`app_lifecycle_service.py:719-743`); `_reload_instance_unlocked()` then creates the replacement unconditionally (`app_lifecycle_service.py:768-784`). Full-app reload similarly stops and then starts without a teardown admission result (`app_lifecycle_service.py:614-643`).

**Supported:** This is the same invariant breach with a different replacement mechanism. The recently added per-instance reload code deliberately stops before creating the new object, which strongly supports “old ownership must be removed before replacement,” but it currently assumes an awaited shutdown is proof of removal. If issue #1696 claims a framework-wide generation invariant, app reload must consume the same teardown report or be explicitly left as a follow-up.

### Why `STOPPED` is insufficient

**Direct:** `ResourceStatus.STOPPED` is documented as “stopped without errors,” is terminal for shutdown handling, and is permitted to transition back to `STARTING` (`enums.py:194-226`; `mixins.py:46-48`). `_force_terminal()` bypasses transition validation to write that same status even though hooks may not run and subscriptions may remain (`base.py:332-353`). `shutdown_completed` similarly means `_finalize_shutdown()` reached its bookkeeping point, not that teardown was clean.

**Inferred:** The data model currently conflates three facts that should be independent: lifecycle orchestration ended, owned work is quiescent, and restart is admissible. The issue became possible because one boolean and one status are carrying all three meanings.

## Feasibility Analysis

### What would need to change

| Area | Likely files | Effort | Risk | Why |
|---|---:|---:|---:|---|
| Teardown data model | 1–2 new/modified files under `resources/`, `types/enums.py` | Medium | Low | Immutable outcome/report types are local and testable. |
| Resource aggregation | `resources/base.py`, `resources/operations.py`, `resources/lifecycle.py`, `resources/mixins.py` | High | High | Must preserve every hook/task/child result and close admission bypasses and races. |
| Service-specific teardown | `resources/service.py`, `task_bucket/task_bucket.py` | Medium | High | Must bound observation of noncooperative tasks without pretending cancellation succeeded. |
| Supervision | `core/service_watcher.py`, possibly `exceptions.py` | Medium | High | Refusal must become terminal for that in-process incarnation, not another retry/cooldown. |
| App replacement cascade | `core/app_lifecycle_service.py`, registry/snapshot tests | Medium | High | Replacement must stop when old teardown is unconfirmed. |
| Telemetry/API | `events/hassette.py`, `schemas/domain_models.py`, `runtime_query_service.py`, generated schemas/types | Medium | Medium | Operators need to distinguish “stopped cleanly” from “quarantined; process recovery required.” |
| Frontend/docs | diagnostics/status components, generated types, lifecycle docs | Medium | Low | Mostly additive if teardown is orthogonal to `ResourceStatus`. |
| Tests | 6–10 unit/integration files | High | Medium | Cancellation resistance and lifecycle races require event-gated deterministic tests. |

### What already supports this

- **Direct:** Lifecycle entry points are `@final` for normal subclasses, so the framework can enforce admission centrally rather than relying on user overrides (`base.py:430-499`; `service.py:94-165`).
- **Direct:** `TaskBucket` already tracks every event-loop task in a strong `set`, can snapshot pending tasks, and already distinguishes done from pending during cancellation (`task_bucket.py:41-57,304-350`). Returning an immutable cancellation report is an incremental extension.
- **Direct:** `ServiceWatcher` already has typed restart policy, fatal shutdown routing, restart budgets, a duplicate-restart guard, and a documented non-zero process-exit path (`service_watcher.py:193-265,322-445,466-495`). Teardown refusal can bypass normal retry policy and reuse fatal escalation.
- **Direct:** Status events and runtime snapshots already carry additive metadata (`retry_at`, `ready`, `ready_phase`), providing a precedent for `teardown_state`, `teardown_reason`, or `restart_eligible` fields.
- **Supported:** Existing app reload code already uses stop-before-create and per-key locks. The evidence points strongly to adapting that path to consume a teardown result rather than inventing another replacement protocol (`app_lifecycle_service.py:630-641,763-784`).
- **Direct external evidence:** Erlang supervisors synchronously terminate a child before restarting it; timeout escalation relies on an unconditional process kill. That guarantee comes from process isolation and cannot be reproduced by `asyncio.Task.cancel()` inside one Python process.

### What works against this

- **Direct:** Shutdown evidence is currently discarded at several layers: `run_hooks(..., continue_on_error=True)` logs errors but returns no result; `TaskBucket.cancel_all()` logs pending tasks but returns no result; `_shutdown_children()` compresses all child outcomes to `bool`; `_finalize_shutdown()` discards even that boolean for admission (`operations.py:83-114`; `task_bucket.py:323-350`; `base.py:355-412`).
- **Direct:** Resource-owned task admission remains open during teardown. A stale task retains its TaskBucket context and can spawn more work unless the bucket is sealed. `TaskBucket.spawn()` has no closed/sealed state (`task_bucket.py:133-176`).
- **Supported:** Even a sealed bucket is not isolation. A surviving coroutine can continue making direct API calls or mutating shared objects, and a cancelled asyncio future wrapping sync work does not prove the worker thread stopped. `SyncExecutor` is global and tracks submissions globally, not by owning Resource (`sync_executor.py:89-220`).
- **Direct:** Framework service instances are wired both into `hassette.children` and concrete Hassette attributes/collaborators. `ServiceWatcher.get_service()` assumes at most one child instance of a service type (`service_watcher.py:118-131`). Fresh replacement therefore has substantial rewiring and identity risk.
- **Direct:** Existing docs promise that most failures result in restart and describe `STOPPED` as a clean state. The lifecycle page and generated schemas require coordinated migration (`docs/pages/core-concepts/internals/lifecycle.md:5-11,75-98`).

## Required safety model

### Proposed data shape

**Recommendation — Inferred design:** Keep teardown evidence orthogonal to `ResourceStatus` to avoid multiplying combined states such as `FAILED_BUT_QUIESCED`, `STOPPED_UNCONFIRMED`, and `CRASHED_WITH_PENDING_TASKS`.

An implementation-level design could use immutable values equivalent to:

```python
class TeardownState(StrEnum):
    NOT_ATTEMPTED = auto()
    IN_PROGRESS = auto()
    QUIESCED = auto()
    UNCONFIRMED = auto()


class TeardownCause(StrEnum):
    HOOK_FAILED = auto()
    CLEANUP_FAILED = auto()
    CLEANUP_TIMED_OUT = auto()
    TASKS_PENDING = auto()
    SERVE_TASK_PENDING = auto()
    CHILD_UNCONFIRMED = auto()
    CHILD_FAILED = auto()
    FORCED_TERMINAL = auto()
    OUTER_TIMEOUT = auto()


@dataclass(frozen=True, slots=True)
class TeardownReport:
    generation: int
    state: TeardownState
    causes: tuple[TeardownCause, ...] = ()
    pending_tasks: tuple[str, ...] = ()
    affected_children: tuple[str, ...] = ()
```

The exact names are a design choice. The important properties are:

1. `shutdown()` returns and stores the same immutable report.
2. `QUIESCED` is produced only from positive evidence; it is never the default after a timeout.
3. Every timeout, swallowed shutdown exception, pending task, unconfirmed child, and force-terminal path monotonically degrades the report to `UNCONFIRMED`.
4. `initialize()` cannot erase `UNCONFIRMED`; only constructing a new process can currently restore a trustworthy baseline.
5. Repeated shutdown callers await or receive the same in-progress attempt’s result instead of returning an ambiguous `None`.
6. `shutdown_completed` may remain temporarily as a compatibility/bookkeeping alias, but it must not participate in restart admission and should ultimately be replaced by the report state.

### What counts as confirmed quiescence

**Recommendation — Inferred design:** Require all of the following:

- lifecycle shutdown hooks completed without an exception;
- `cleanup()` completed within budget;
- the initialization task is done;
- the TaskBucket is sealed against new generation-N work and has no pending async tasks;
- for `Service`, `_serve_task.done()` is true;
- every child returned `TeardownState.QUIESCED` for its current generation;
- no outer force-terminal or total-timeout path intervened.

**Unknown:** The code has no per-Resource ownership record for sync executor threads. We searched `TaskBucket`, `SyncExecutor`, `SyncExecutorService`, and execution telemetry. The global executor knows outstanding submissions and individual execution code can observe `thread_leaked`, but Resource teardown cannot currently prove that all sync work from one Resource ended. A design must either add per-owner submission tracking, classify any cancelled active sync submission as unconfirmed, or explicitly state that “quiesced” covers only async ownership. The last option weakens the proposed invariant.

### Admission and race rules

**Recommendation — Supported:** Gate at the lowest common entry point, not only in `ServiceWatcher`.

- `restart(resource)` should initiate or join teardown, require `report.state is QUIESCED`, and raise a typed `RestartRefusedError(report)` without calling `initialize()` otherwise.
- `Resource.initialize()` and `Service.initialize()` should independently reject a prior `UNCONFIRMED` report so `start()` and direct calls cannot bypass the invariant.
- A per-resource lifecycle operation lock or generation-aware operation coordinator should serialize initialize/shutdown/restart. The existing `initializing`, `shutting_down`, and watcher `_restarting` flags are not an atomic restart transaction.
- TaskBucket sealing should occur when shutdown stops accepting new work. If shutdown hooks need to spawn cleanup tasks, they need an explicit teardown scope rather than silently reopening the old generation’s bucket.
- Force-terminal must store `UNCONFIRMED/FORCED_TERMINAL` before setting any terminal bookkeeping status.

## Options Evaluated

### Option A: Explicit teardown report, hard admission gate, process escalation on refusal

**How it works:** Preserve same-instance restart for ordinary failures, but turn shutdown into an evidence-producing operation. Each lifecycle layer returns structured evidence; the parent aggregates it. Restart and initialize admission require a `QUIESCED` report from the immediately preceding generation. The report is exposed through status telemetry.

If `ServiceWatcher` receives `RestartRefusedError`, it does not spend more cooldown cycles or retry the same object. It emits a terminal/fatal event with teardown context, records a fatal shutdown reason, and requests whole-process shutdown. This safety escalation should override `RestartType`: a `TEMPORARY` service with stale live work is not safely “absent,” and a `TRANSIENT` cooldown cannot make old work quiescent.

For app reload, the old registry entry may be marked quarantined, but no replacement is created after an unconfirmed result. The safest default is the same process-fatal escalation because an old app task can still call Home Assistant.

**Pros:**

- Directly satisfies every issue acceptance criterion.
- Keeps the successful in-process recovery path and existing budgets/backoff.
- Makes force-terminal honest without requiring a large new `ResourceStatus` state explosion.
- Produces actionable operator data: why restart was refused and which work remained.
- Builds on existing TaskBucket tracking, final lifecycle methods, status payloads, and fatal shutdown handling.

**Cons:**

- Touches more than the four files named in the issue once direct initialize, app reload, telemetry, and races are handled honestly.
- “Confirmed” requires changing several logging-only APIs to return evidence.
- Process shutdown is disruptive for an optional service, though continuing with stale work is not demonstrably safe.
- External process termination is still needed if a coroutine or thread defeats Python’s cooperative shutdown.

**Effort estimate:** Large. The core data model is small; proving the invariant across all entry points, races, app replacement, telemetry, and tests is the substantial work.

**Dependencies:** No new library. Uses existing asyncio, dataclasses, Pydantic schemas, and supervision machinery.

### Option B: Broader generation-scoped lifecycle redesign

**How it works:** Replace the loose status/boolean/task fields with an explicit lifecycle controller and per-generation ownership object. A stable Resource identity owns a sequence of `ResourceGeneration`/incarnation records; each generation owns its TaskBucket, serve task, children/registrations, teardown report, and generation number. Lifecycle operations are serialized by the controller. A new generation can be created only after the prior ownership scope closes cleanly.

This is the first-principles shape if restart had been a requirement from day one. It eliminates flag synchronization and gives every task/registration a generation boundary. Generation tokens could also fence late callbacks and registration writes, making stale work observable and rejectable even before process exit.

**Pros:**

- Encodes the invariant structurally instead of relying on several flags staying aligned.
- Makes concurrent start/shutdown/restart behavior explicit and testable.
- Gives a natural home for deadlines, teardown causes, generation telemetry, and stale-callback fencing.
- Reduces long-term ambiguity around `STOPPED`, `shutdown_completed`, and `_force_terminal()`.

**Cons:**

- Very large blast radius across Resource, Service, TaskBucket, app resources, test harnesses, telemetry, and direct service references.
- Generation fencing must reach every shared boundary to make a surviving old generation harmless; partial adoption creates false confidence.
- Still cannot forcibly terminate a Python coroutine or thread. Process escalation remains necessary after unconfirmed teardown.
- Risks turning a focused safety bug into a prolonged lifecycle rewrite.

**Effort estimate:** Very large. Appropriate as a separate architecture initiative, not required to close the immediate hole.

**Dependencies:** No mandatory external library. `asyncio.TaskGroup` does not solve error-isolating long-lived supervision or force cancellation, so adopting it is neither necessary nor sufficient.

### Option C: Process-only service recovery

**How it works:** Remove same-process service restart. Any recoverable `FAILED` service triggers graceful Hassette shutdown and a non-zero exit; systemd, Docker, or another process supervisor creates a completely fresh runtime. Keep restart budgets at the process supervisor, or simplify/remove Hassette’s in-process budgets.

**Pros:**

- Strongest isolation available: a new address space cannot share old Python tasks or mutable objects.
- Greatly simplifies Resource restart semantics and eliminates same-instance generation races.
- Aligns with systemd’s model: restart is stop then start, and stop timeout escalates to `SIGKILL`.

**Cons:**

- Restarts every healthy app and service for transient WebSocket, database, API, or file-watcher failures.
- Weakens Hassette as a standalone library/CLI when no external supervisor is configured.
- Makes the substantial existing `RestartSpec`, cooldown, budget, and UI machinery partly redundant.
- Graceful process exit can still hang on cancellation-resistant Python work unless the external supervisor enforces a hard kill timeout.

**Effort estimate:** Medium for code removal/rerouting, but high migration impact.

**Dependencies:** Operational dependency on an external process supervisor with restart and hard-stop policy.

### Option D: Fresh in-process object replacement

**How it works:** On service failure, build a new Service object instead of reinitializing the old one, atomically replace it in `hassette.children` and concrete Hassette attributes, then rewire dependents. The old object is quarantined.

**Pros:**

- New object starts with clean Python fields, events, TaskBucket, and status.
- Mirrors the successful object-replacement shape used for app reloads after clean teardown.
- Avoids some same-instance state-reset bugs.

**Cons:**

- Does not solve the motivating failure. Surviving work from the old object remains in the same event loop/process and can still use shared APIs, registrations, sockets, database handles, and owner identities.
- Framework services have direct references and type-uniqueness assumptions; replacement requires broad atomic rewiring (`service_watcher.py:118-131`).
- Duplicate listeners/jobs and old/new service competition become more likely unless every side effect is generation-fenced.
- More complex than same-instance restart while offering less isolation than process restart.

**Effort estimate:** Very large and high risk.

**Dependencies:** No new library, but requires a new service factory/registry, reference rewiring, and generation fencing.

### Do-less option: Check the existing boolean and task `.done()` flags

**How it works:** Preserve current shutdown and add `if not children_clean or not _serve_task.done(): raise` in `restart()`.

**Pros:** Small diff; catches the two named examples in some executions.

**Cons:** Does not catch hook/cleanup errors, TaskBucket stragglers, stale registrations, sync threads, direct `initialize()`/`start()` bypass, force-terminal lying through `shutdown_completed`, or concurrent restart races. The child boolean is currently discarded and a fully cancellation-resistant task can defeat `wait_for()` itself.

**Effort estimate:** Small.

**Assessment:** Not sufficient for the stated desired outcome. It is suitable only as an emergency stopgap while Option A is designed.

## ServiceWatcher semantics

**Recommendation — Inferred design:** Restart refusal is qualitatively different from another failed startup. Startup failure may become healthy after backoff; unconfirmed teardown cannot become safer with time because the framework has no force-kill or isolation boundary.

Suggested behavior:

1. Record one attempted recovery in the existing budget for audit, but do not recursively re-enter normal retry/cooldown.
2. Catch only the typed `RestartRefusedError`; keep unexpected restart exceptions on the existing failure path.
3. Emit `CRASHED` (or a status event with equivalent terminal semantics) carrying teardown state/cause and `restart_eligible=false`.
4. Record a fatal reason synchronously and request root shutdown, reusing the race-safe pattern at `service_watcher.py:466-495`.
5. Keep `_restarting` set until the refusal event and fatal reason are recorded, then clear it in `finally`.
6. Cooldown recovery must use the same path; it cannot call `restart(service)` and merely log refusal (`service_watcher.py:267-320`).

**Open policy choice:** A new orthogonal `quarantined` field is preferable to adding `ResourceStatus.QUARANTINED`, but the UI still needs a prominent fatal label. Reusing `CRASHED` for the service plus teardown metadata avoids expanding every status map while accurately communicating “cannot recover in process.”

## Compatibility and migration

### Source/API compatibility

- **Supported:** Returning a `TeardownReport` from `shutdown()` is low source-compatibility risk because current production callers ignore the return value. Tests and helper overrides need annotation updates. `Hassette.shutdown()` and app lifecycle wrappers must preserve/aggregate the report rather than overwrite it.
- **Direct:** Subclasses cannot override final Resource/Service shutdown orchestration, so app-author hooks do not need signature changes.
- **Breaking but intentional:** A direct `initialize()` after unconfirmed teardown will now raise instead of silently restarting. This is the desired contract change.
- **Migration:** Deprecate `shutdown_completed` as restart evidence immediately. Keep it only as “the shutdown attempt reached terminal bookkeeping” until callers/tests migrate to `teardown_report.state`.

### Status and telemetry migration

- Add optional `teardown_state`, `teardown_causes`, `restart_eligible`, and possibly `generation` to `ServiceStatusPayload`, `ServiceStatusData`, and `ServiceInfo`.
- Regenerate WebSocket/OpenAPI/frontend types and update diagnostics displays.
- Change lifecycle documentation so `STOPPED` no longer alone implies clean quiescence, or only emit `STOPPED` with a clean report and use `CRASHED`/`FAILED` on force-finalization.
- Include pending task names and child names in logs/events, but avoid unbounded payloads; cap and summarize counts.

### Rollout sequence

1. Add characterization tests showing current child-timeout and noncooperative-serve behavior is unsafe or unbounded.
2. Introduce report/cause types and make hook, TaskBucket, Service, child, and root shutdown paths produce evidence without changing restart policy yet.
3. Add initialize/restart admission and force-terminal classification.
4. Update `ServiceWatcher` refusal escalation and tests.
5. Wire app reload to the report or explicitly split it into a blocking follow-up before claiming a framework-wide invariant.
6. Add telemetry/frontend/docs.
7. Remove restart authorization based on `shutdown_completed` and update stale tests/docs.

## Concerns

### Technical risks

- **Cancellation is not termination.** Python provides no safe task kill. A report must never infer quiescence from `cancel()` or a timeout expiring.
- **Timeout APIs can be soft.** `wait_for()` waits for cancellation completion; `asyncio.timeout()` also relies on cancellation. Hard observation requires separately created tasks plus `asyncio.wait(..., timeout=...)`, followed by quarantine of pending work.
- **Task admission race.** Without sealing the old TaskBucket, a task can be spawned after the “pending tasks” snapshot.
- **Lifecycle operation race.** Without a lock/generation coordinator, two direct restart/start/shutdown calls can interleave around a clean report.
- **Sync thread gap.** Async future cancellation does not prove sync worker termination. This is the largest unmodeled ownership gap.
- **Root shutdown semantics.** `Hassette.shutdown()` currently force-patches children and always sets itself `STOPPED`/`shutdown_completed=True` in `finally` (`core.py:777-809`). Root process-finalization state must not be recycled as evidence that child services are restartable.

### Complexity risks

- A cause enum can grow into an exhaustive failure taxonomy. Keep it limited to decisions that change restart eligibility or operator action.
- Adding a full lifecycle controller in the same change risks obscuring the safety fix. Option A should establish the invariant first; broader state reduction can follow.
- Duplicating report logic between Resource and Service would repeat the current “keep in sync” hazard documented in both classes. Shared aggregation functions should own the decision rule.

### Maintenance risks

- New telemetry fields create schema-generation and frontend maintenance obligations.
- If process-fatal refusal is configurable, unsafe settings may become normalized. The safe default should not be overridable until a genuine isolation mechanism exists.
- App and framework-service lifecycle paths can drift again unless both consume one shared report type and admission predicate.

## Test Strategy

**Direct project convention:** Timing-sensitive lifecycle tests should use `asyncio.Event` gates and explicit “entered” signals rather than `sleep(0)` scheduler guesses (`CLAUDE.md`, Bug Investigation Workflow).

### Required deterministic tests

1. **Child timeout report:** Gate a child inside `on_shutdown()`. Let the configured timeout expire. Assert parent and child reports are `UNCONFIRMED`, force-terminal is recorded as a cause, and `_on_children_stopped()` is skipped.
2. **Direct restart refusal:** Run `restart(parent)` against the timed-out child. Assert a typed refusal, no second initialize hook, no generation increment, and no cleared teardown report.
3. **Direct initialize/start bypass:** Call `initialize()` and `start()` after force-terminal/unconfirmed teardown. Assert both refuse before resetting events or spawning tasks.
4. **Noncooperative serve task:** Implement `serve()` that catches cancellation and waits on a test release event. Use `asyncio.wait({restart_task}, timeout=...)` so the test observes whether restart returns/refuses without cancelling the restart task. Assert no second `_serve_task` is spawned; release the old task in `finally` to keep teardown clean.
5. **TaskBucket straggler:** Make an owned non-serve task resist cancellation. Assert `cancel_all()` reports its name and Resource teardown is unconfirmed.
6. **Hook/cleanup exception:** Assert a shutdown hook or cleanup exception makes the report unconfirmed even when tasks and children finish.
7. **Concurrent callers:** Start two shutdown/restart callers behind an event gate. Assert they join one teardown attempt and receive the same report; only one next generation can start.
8. **Force-terminal:** Assert it never produces `QUIESCED` or restart eligibility, even if the cancelled task happens to finish on the next loop tick.
9. **Watcher refusal:** Mock or induce typed refusal in both backoff and cooldown paths. Assert one restart call, no further cooldown/retry, fatal reason recorded, CRASHED/refusal event emitted, and root shutdown requested.
10. **App replacement:** Make an app instance teardown unconfirmed. Assert registry/lifecycle state records quarantine and no replacement instance is created.

### Integration/system tests

- Use a real Bus/Scheduler registration owned by a test Resource, force teardown uncertainty, and prove no second owner generation is registered.
- Verify service-status WebSocket payloads and system snapshots expose teardown/refusal data.
- Verify a refusal-driven fatal shutdown exits non-zero. If an external supervisor test environment exists, verify a fresh process can then start cleanly.

**Observability gap:** A pure in-process test cannot prove OS-level process recovery or force-kill behavior. That requires a subprocess/system test and a configured supervisor timeout.

## Open Questions

- [ ] **Should every teardown refusal be process-fatal?** The safety analysis supports yes because quarantine is not isolation. We found no code mechanism that can make stale service/app work harmless in place. Product preference for keeping optional services alive is not documented.
- [ ] **Must issue #1696 include app reload?** The same invariant is violated in `AppLifecycleService`, but the issue’s acceptance files focus on Resource/Service/Watcher. Leaving apps out should be an explicit scoped follow-up, not an implicit omission.
- [ ] **How should sync work be attributed to a Resource?** We searched TaskBucket, SyncExecutor, SyncExecutorService, and execution telemetry and found no per-owner active-thread registry suitable for teardown proof.
- [ ] **Should hook failure always block restart?** It is safest to say yes because Bus/Scheduler cleanup lives in hooks and a failed hook can leave registrations active. A narrower rule would need per-hook proof of which ownership was released.
- [ ] **Should `STOPPED` remain usable with `teardown_state=UNCONFIRMED`, or should force-finalized resources use `CRASHED`?** Orthogonal metadata reduces state explosion; strict status semantics may favor changing the emitted status.
- [ ] **What is the standalone deployment contract?** Code comments and docs mention systemd/Docker recovery, but the repository does not establish that every user runs an external supervisor. Process-fatal fallback needs clear operational documentation.
- [ ] **What hard-kill policy applies when process shutdown itself cannot complete?** Python cancellation cannot provide the Erlang/systemd “brutal kill” guarantee. External systemd/Docker timeout policy is the practical boundary unless Hassette intentionally adopts a last-resort hard exit.

## Recommendation

**Supported:** Choose Option A. It is the smallest option that establishes the actual invariant rather than patching the two examples. The evidence is the convergence of four code facts: shutdown layers discard negative evidence, force-terminal knowingly skips cleanup, restart/initialize erase shutdown bookkeeping, and Python cancellation cannot force quiescence.

Do not combine Option A with fresh service replacement. Existing app replacement is safe only under the assumption that the old instance stopped; the current issue is precisely about that assumption failing. A fresh object is useful after confirmed teardown, not as a substitute for it.

Treat process-only recovery as the escalation path, not the default for all service failures. This retains Hassette’s useful in-process restart budgets for cleanly stoppable failures while using the OS process boundary when Python can no longer prove isolation.

Defer Option B until Option A provides evidence and telemetry. If implementation reveals that a lifecycle lock, TaskBucket sealing, and generation identity cannot be added without preserving the current boolean maze, that is the signal to promote the generation-scoped redesign into its own design effort.

### Suggested next steps

1. Write a design doc defining `TeardownReport`, the exact `QUIESCED` predicate, lifecycle serialization, and watcher refusal policy.
2. Decide whether app reload and per-owner sync-thread tracking are blocking scope or explicit linked follow-ups.
3. Build the two RED regressions first: child timeout followed by restart, and cancellation-resistant `serve()` observed with `asyncio.wait`.
4. Implement report propagation before changing admission, then add the gate and watcher escalation as separate verifiable units.
5. Add status telemetry and deployment guidance for process-fatal refusal.

## Sources

- [GitHub issue #1696: Prevent restart after unconfirmed resource teardown](https://github.com/NodeJSmith/hassette/issues/1696)
- [Python asyncio task cancellation, timeouts, `wait_for`, and `wait`](https://docs.python.org/3/library/asyncio-task.html)
- [Erlang/OTP Supervisor Behaviour](https://www.erlang.org/doc/system/sup_princ.html)
- [systemd.service source documentation](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml) — restart is stop then start; stop timeout escalates to forced process termination.
- `design/research/2026-03-29-lifecycle-timeout-enforcement/research.md` — prior timeout/force-terminal analysis.
- `design/research/2026-04-26-resource-service-lifecycle/research.md` — lifecycle prior art and explicit-state assessment.
- `design/research/2026-05-01-async-task-management/research.md` — TaskBucket, supervision, and cooperative cancellation analysis.
- `design/research/2026-08-24-per-instance-restart/research.md` and commit `d84aa21f` — stop-before-create app replacement precedent.
- Commit `5681c92a` — introduction of per-service `RestartSpec` supervision.
- Commit `1533a565` — later hardening of SyncExecutorService restart and concurrency behavior.

## Research limitations

- The worktree has no `.codegraph/` index, so structural discovery used direct file reading, grep, and git history rather than CodeGraph call-path output.
- Parallel research subagents were unavailable in this execution environment; the architecture, integration, history, and dependency passes were performed directly.
- No implementation or test suite was run; this brief evaluates feasibility and specifies the evidence the implementation must produce.
