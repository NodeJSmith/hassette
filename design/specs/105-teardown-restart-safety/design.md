# Design: Teardown Restart Safety

**Date:** 2026-08-26
**Status:** archived
**Scope-mode:** hold
**Research:** `design/research/2026-08-26-teardown-restart-safety/research.md`

## Problem

Hassette can currently start a new lifecycle incarnation after shutdown failed to prove that the old one stopped. Child timeouts, cleanup failures, pending TaskBucket work, and a cancellation-resistant `Service.serve()` task are logged, but shutdown still sets `shutdown_completed=True`. `restart()` then calls `initialize()` unconditionally.

This can leave old and new work active in the same process. `ResourceStatus.STOPPED` and `shutdown_completed` describe lifecycle bookkeeping, not quiescence, so neither is sufficient evidence that restart is safe.

The same risk is present outside `restart()`: `start()` and direct `initialize()` calls reset shutdown state, concurrent shutdown callers return before the first attempt finishes, and cancellation of the initiating caller can interrupt the only teardown attempt.

## Goals

- Produce an immutable shutdown outcome that states whether lifecycle-managed async work is confirmed quiescent.
- Refuse every same-instance initialization path after teardown is restart-unsafe.
- Make concurrent lifecycle callers join one cancellation-shielded initialization or shutdown attempt.
- Preserve existing same-instance restart behavior, backoff, and budgets after clean teardown.
- Give Python callers and logs enough detail to identify why restart was refused.
- Cover the unsafe paths with deterministic unit and watcher integration tests.

## Non-Goals

- App reload and replacement. Issue #1689 owns that path and already depends on this work.
- Per-resource ownership or termination proof for sync-executor threads.
- A root-wide draining state that rejects every app or resource admission after fatal escalation.
- New WebSocket, runtime-query, generated frontend, or dashboard fields.
- A universal hard-kill policy for standalone or externally supervised deployments.
- Fresh in-process service replacement.
- A full lifecycle generation object or general lifecycle state-machine rewrite.

## User Scenarios

### Hassette operator: Person running automations

- **Goal:** Recover automatically when a service fails without running two copies of its work.
- **Context:** A background service emits `FAILED` and `ServiceWatcher` applies its `RestartSpec`.

#### Clean service recovery

1. **Observe the service failure**
   - Sees: The existing failure event and restart diagnostics.
   - Decides: No manual action is needed while automatic recovery remains safe.
   - Then: `ServiceWatcher` waits for the configured backoff and starts one restart attempt.
2. **Complete clean teardown**
   - Sees: Shutdown complete without teardown refusal diagnostics.
   - Decides: Nothing; recovery continues automatically.
   - Then: A report with `is_restart_safe` `True` authorizes one initialization attempt and existing restart accounting remains unchanged.
3. **Resume normal operation**
   - Sees: The service returns to `RUNNING` and readiness resets its budget as it does today.
   - Decides: No action is needed.
   - Then: Hassette continues without restarting the process.

#### Restart-unsafe teardown refusal

1. **Encounter restart-unsafe teardown**
   - Sees: A log and typed error naming the teardown causes, pending task names, or affected children.
   - Decides: The same object cannot recover safely; the supervising or embedding host must replace the process if automatic recovery is required.
   - Then: Hassette requests shutdown, and no new initialization or `serve()` task starts.
2. **Escalate once**
   - Sees: One `CRASHED` event carrying `RestartRefusedError` through the existing exception fields.
   - Decides: No further in-process retry is safe.
   - Then: `ServiceWatcher` records the fatal reason and enters the existing process-shutdown path without another cooldown or retry.

### Framework caller: Code invoking lifecycle operations directly

- **Goal:** Receive the same lifecycle safety guarantees as watcher-driven recovery.
- **Context:** Test utilities, framework internals, or embedding code call `shutdown()`, `restart()`, `start()`, or `initialize()`.

#### Concurrent lifecycle calls

1. **Call shutdown or initialize while an attempt is active**
   - Sees: All awaiters receive the same result or exception from the shared attempt.
   - Decides: The caller may cancel its own wait without cancelling framework lifecycle work.
   - Then: The attempt continues under resource ownership and no duplicate hook sequence starts.
2. **Call initialize after teardown**
   - Sees: A report with `is_restart_safe` `True` permits one new attempt; `is_restart_safe` `False` raises `RestartRefusedError` with the stored report.
   - Decides: Replace the process or abandon the object after refusal.
   - Then: Restart-unsafe evidence remains sticky and cannot be reset by another entry point.

## Functional Requirements

- **FR#1** Every completed `Resource.shutdown()` and `Service.shutdown()` call must return and store an immutable teardown report.
- **FR#2** A teardown report may have `is_restart_safe` `True` only when shutdown hooks, cleanup, tracked async work, child shutdown, and the service task have all completed without negative evidence.
- **FR#3** Hook errors, whole-body shutdown timeout, cleanup errors or timeouts, pending TaskBucket work, child failure or timeout, a pending service task, force-terminal use, and the root total timeout must produce a report with `is_restart_safe` `False` with concrete causes.
- **FR#4** Concurrent shutdown callers must join one shutdown attempt and receive its report; cancelling an awaiter must not cancel the shared attempt.
- **FR#5** Concurrent initialization callers must join one initialization attempt; direct `initialize()` must be tracked by the same coordinator as `start()`.
- **FR#6** Initialization requested during shutdown must wait for that shutdown outcome before deciding whether a new incarnation may start.
- **FR#7** `restart()`, `start()`, and direct `initialize()` must reject a stored report with `is_restart_safe` `False` without clearing it or starting lifecycle work.
- **FR#8** Restart refusal must raise `RestartRefusedError` containing the resource identity and teardown report.
- **FR#9** A report with `is_restart_safe` `True` must continue to authorize same-instance restart using existing service backoff, budget, cooldown, and readiness-reset behavior.
- **FR#10** Force-terminal handling must store a restart-unsafe report before cancelling work or writing terminal lifecycle bookkeeping.
- **FR#11** TaskBucket shutdown must stop accepting new owner work before its final pending-task check and report every remaining task by name.
- **FR#12** `ServiceWatcher` must route `RestartRefusedError` from both normal backoff and cooldown recovery to one fatal outcome without another retry or cooldown.
- **FR#13** Hassette's total shutdown timeout must return and store a report with `is_restart_safe` `False` with total-timeout and force-terminal evidence while still running its existing stream-closing fallback.
- **FR#14** Python callers must be able to inspect the returned report, any current unconsumed report, and refusal details without a frontend or schema change.
- **FR#15** Shutdown requested during initialization must cancel and observe the initialization attempt before running shutdown hooks.
- **FR#16** Any lifecycle front door invoked from the active initialization coordinator, shutdown coordinator, or shutdown body that would join or cancel its own lifecycle attempt, including `initialize()`, `start()`, `restart()`, and `shutdown()`, must fail explicitly before creating another task.
- **FR#17** A forced or failed shutdown-body task must remain retained and exception-observed until it actually completes.

## Edge Cases

- A child returns a report with `is_restart_safe` `False` without raising. The parent must also become restart-unsafe and retain the child's identity and causes.
- A child `shutdown()` raises unexpectedly. Sibling shutdown continues, but the parent records child failure and cannot authorize restart.
- A child wave times out after some children finish safely. Safe child reports remain safe; unfinished children are force-terminal and the parent is restart-unsafe.
- A shutdown hook raises while later hooks still need to run. The hook runner continues as it does today and returns the error evidence to aggregation.
- A shutdown hook blocks or resists cancellation. The whole shutdown body deadline records timeout and force-terminal evidence rather than leaving the coordinator pending forever.
- Cleanup times out or raises. Child shutdown and terminal bookkeeping still run, but the report remains restart-unsafe.
- A tracked task ignores cancellation or creates more owner work during teardown. TaskBucket sealing rejects new work, and any task still pending after the bounded wait appears in the report.
- `serve()` catches cancellation and remains pending. Shutdown observes it with a bounded wait, returns a report with `is_restart_safe` `False`, and never spawns a replacement task.
- A caller awaiting shared initialization or shutdown is cancelled. `asyncio.shield()` cancels only that wait; the resource-owned task continues.
- Shutdown begins while initialization is blocked. It cancels and observes that attempt before running shutdown hooks; a resistant initializer makes teardown restart-unsafe.
- An initialization hook calls `initialize()`, `start()`, `restart()`, or `await self.shutdown()`. The front door raises `LifecycleReentryError` before joining, cancelling, or creating a lifecycle task; hooks must fail or return rather than recursively await lifecycle orchestration.
- A shutdown hook calls `initialize()`, `start()`, `restart()`, or `await self.shutdown()`. The front door raises `LifecycleReentryError` before it can join the coordinator that is awaiting the hook's own shutdown body.
- Two restart callers receive one clean shutdown report and join one initialization task.
- Two restart callers receive one restart-unsafe report and both receive refusal without starting initialization.
- Repeated shutdown before a new clean initialization returns the same stored report and does not rerun hooks.
- A safe report is cleared only when an accepted new initialization begins. A restart-unsafe report has no in-process reset path.
- Force-terminal runs after a child already reported `is_restart_safe` `True`. It leaves that completed child's report unchanged and degrades only unfinished resources.
- Fatal escalation receives duplicate triggering events. The active watcher guard handles overlap; afterward the process-latched fatal reason and root shutdown event prevent another recovery attempt or fatal transition.
- The shutdown coordinator itself raises outside the shutdown body -- observing the active initializer, requesting shutdown, or reading a config value before the body task is even created. The coordinator records `COORDINATOR_FAILED`, merges it with any evidence a concurrent force-terminal already stored, and re-raises, so `_teardown_report` is never left unset and a later `coordinate_initialize()` call still sees a restart-unsafe report instead of skipping the `RestartRefusedError` guard entirely.

## Operational Lifecycle

The teardown report is orthogonal to `ResourceStatus`:

| Lifecycle condition | Coordinator state | Teardown report | New initialization |
|---|---|---|---|
| Never started or currently live | no shutdown attempt, or prior safe report consumed | `None` | Existing rules apply |
| Initialization active | initialization task pending | `None` | Join the task |
| Shutdown active | shutdown task pending | `None` until final evidence is stored | Wait for shutdown |
| Shutdown proved restart-safe | shutdown task complete | `is_restart_safe` `True` | One new attempt may consume the report |
| Shutdown did not prove restart-safe | shutdown task complete or force-cancelled | `is_restart_safe` `False` | Refuse permanently for this object |

`ResourceStatus.STOPPED` continues to mean that lifecycle orchestration reached its terminal phase. It may coexist with `is_restart_safe` `False`; only the report decides restart eligibility.

For watcher-driven recovery, clean teardown follows the current retry lifecycle. Refusal is terminal for the in-process object because waiting longer cannot prove stale work stopped. It bypasses remaining retries and cooldowns, records a fatal reason, requests root shutdown, and attempts one `CRASHED` event. Process replacement is the only supported recovery after refusal and remains the embedding host or supervisor's responsibility.

## Acceptance Criteria

- **AC#1** Unit tests prove a child timeout returns a report with `is_restart_safe` `False`, records child and force-terminal causes, and prevents `restart()`, `start()`, and direct `initialize()` from running a second initialize hook. Covers FR#1, FR#3, FR#7, and FR#10.
- **AC#2** Unit tests prove a cancellation-resistant `serve()` task does not make shutdown exceed its observation budget, produces a report with `is_restart_safe` `False`, and never gets a replacement `serve()` task. Covers FR#2, FR#3, and FR#7.
- **AC#3** Unit tests prove hook failure, cleanup failure, cleanup timeout, and TaskBucket stragglers each produce their named cause and failed-operation name while later shutdown stages still run. Covers FR#1, FR#2, FR#3, and FR#11.
- **AC#4** Event-gated unit tests prove concurrent callers join one shielded initialization or shutdown attempt, caller cancellation does not cancel that attempt, shutdown observes an active initializer before hooks, and lifecycle re-entry from initialization or shutdown hooks raises explicitly. Covers FR#4, FR#5, FR#6, FR#15, and FR#16.
- **AC#5** Unit tests prove repeated shutdown returns the stored report, initialization consumes only a report with `is_restart_safe` `True`, and force-terminal cannot produce restart eligibility. Covers FR#7, FR#9, and FR#10.
- **AC#6** Integration tests exercise refusal from both `ServiceWatcher.execute_restart()` and `cooldown_and_retry()`, observing one restart call, no further retry after the handler returns, one fatal reason, and root shutdown requested even when `CRASHED` event dispatch fails. Covers FR#8 and FR#12.
- **AC#7** Root lifecycle tests prove total-timeout fallback closes event streams and returns a report with `is_restart_safe` `False` with total-timeout and force-terminal causes. Covers FR#13.
- **AC#8** Existing clean restart, restart-budget, cooldown, readiness-reset, lifecycle propagation, and orderly shutdown tests remain green. Covers FR#9.
- **AC#9** `uv run nox -s dev` completes with zero test failures.
- **AC#10** `prek -a` completes with no errors.

## Key Constraints

- Clean teardown requires positive evidence. A timeout, swallowed exception, pending task, or force-terminal path must never default to success.
- Teardown eligibility remains separate from `ResourceStatus`; do not add a combined status such as `STOPPED_UNSAFE` or expand frontend status maps.
- No public or test-only reset may clear a report with `is_restart_safe` `False` on the same object.
- Observation of cancellation-resistant tasks must use bounded `asyncio.wait()` semantics rather than treating `cancel()` or `wait_for()` cancellation as termination proof.
- The authoritative coordinator must remain limited to one initialization task and one shutdown task per resource. Bounded stage observation may use scoped tasks, but do not introduce generation tokens, a general operation queue, or a new lifecycle controller object.
- The report must not claim that sync executor threads or arbitrary untracked tasks stopped.
- Do not add app replacement behavior to this PR. The report may be consumed by #1689 later without changing its shape.

## Dependencies and Assumptions

- No new package is required. The design uses Python 3.11 asyncio, frozen dataclasses, and existing Hassette lifecycle machinery.
- Python task cancellation is cooperative. `is_restart_safe` `False` prevents same-instance restart but cannot stop a coroutine or thread that ignores cancellation.
- Refusal records a fatal reason and requests process shutdown. Process replacement is the embedding host or supervisor's responsibility. This PR does not guarantee that the host will kill a process that never exits; that is an accepted deployment limitation.
- `is_restart_safe` `True` covers lifecycle hooks, completion of the lifecycle-owned initialization attempt, work tracked by the resource's TaskBucket, child resources, and `Service.serve()`. Receiving the report proves the lifecycle-owned shutdown attempt reached its return point. The claim does not cover sync executor threads or tasks deliberately created outside supported Hassette ownership paths.
- TaskBucket sealing covers async work created through `TaskBucket.spawn()` and Hassette's task factory. The global TaskBucket and per-resource sync submission attribution remain outside scope.
- The change has no persisted data, database migration, authentication, configuration, or frontend dependency.
- The work is delivered as one narrowed PR for issue #1696.

## Architecture

### Teardown report

Create `src/hassette/resources/teardown.py` with the immutable teardown types. `None` represents no completed teardown attempt, and the in-progress task represents active teardown, so restart safety needs only two final values.

```python
class TeardownCause(StrEnum):
    SHUTDOWN_HOOK_FAILED = auto()
    SHUTDOWN_BODY_TIMED_OUT = auto()
    SHUTDOWN_BODY_FAILED = auto()
    CLEANUP_FAILED = auto()
    CLEANUP_TIMED_OUT = auto()
    INITIALIZATION_TASK_PENDING = auto()
    TASKS_PENDING = auto()
    SERVE_TASK_PENDING = auto()
    CHILD_SHUTDOWN_FAILED = auto()
    CHILD_SHUTDOWN_TIMED_OUT = auto()
    CHILD_RESTART_UNSAFE = auto()
    FORCED_TERMINAL = auto()
    TOTAL_TIMEOUT = auto()
    COORDINATOR_FAILED = auto()


@dataclass(frozen=True, slots=True)
class TeardownReport:
    causes: tuple[TeardownCause, ...] = ()
    failed_operations: tuple[str, ...] = ()
    pending_tasks: tuple[str, ...] = ()
    affected_resources: tuple[str, ...] = ()

    @property
    def is_restart_safe(self) -> bool:
        return not self.causes
```

The concrete implementation may add small pure constructors or merge functions, but it must keep these rules:

- `is_restart_safe` is derived so a report cannot contain contradictory safety and causes.
- Cause, failed-operation, task, and resource tuples are deduplicated and deterministic.
- `failed_operations` records bounded operation identities such as a hook's qualified name or `cleanup`; exception type, message, and traceback remain in existing logs rather than being copied into the report.
- Aggregation returns a new report; it never mutates a report that another caller may already hold.
- Parent reports merge child causes and details, then add `CHILD_RESTART_UNSAFE` or the applicable child failure/timeout cause.
- A later completion may add evidence but cannot remove a cause from the current shutdown attempt.

Calling `shutdown()` on Resource, Service, or Hassette instances returns the stored report through the inherited public front door. A read-only `teardown_report` property exposes the current unconsumed report to Python callers; a caller that needs clean history keeps the immutable return value. `RestartRefusedError` in `src/hassette/exceptions.py` carries `resource_name` and `report`; its message lists the causes and bounded detail fields so existing exception logging remains useful. `LifecycleReentryError` identifies a lifecycle front door invoked from its own active initialization coordinator, shutdown coordinator, or shutdown body.

### Minimal lifecycle coordinator

`LifecycleMixin` owns three authoritative fields:

- `_init_task`: the one resource-owned initialization attempt, including direct `initialize()` calls.
- `_shutdown_task`: the one resource-owned shutdown attempt.
- `_teardown_report`: the final report for the current shutdown attempt.

It also retains `_shutdown_body_task` as non-admission diagnostic ownership. This field never decides whether a lifecycle operation may start; it keeps a cancellation-resistant body reachable and observable until completion.

The coordinator tasks are lifecycle-owned rather than TaskBucket-owned. The shutdown body cancels TaskBucket work, so putting the task performing that cancellation in the same bucket would create self-cancellation and make ownership circular. Create coordinator and body tasks outside Hassette's TaskBucket task factory, using the same direct `asyncio.Task` mechanism that the factory itself uses.

Common module-level helpers in `src/hassette/resources/lifecycle.py` create or join these tasks. Final public `Resource.initialize()` and `Resource.shutdown()` are coordinator front doors only. They schedule named internal `_initialize_body()` and `_shutdown_body()` methods; they never schedule a public lifecycle method as its own body. `Service` supplies its service-specific body implementations, and Hassette supplies its root shutdown body and timeout fallback. `start()` calls the public initialization front door but never assigns `_init_task` itself. The underscored bodies are unsafe to call directly because they bypass admission and ownership.

Task selection and assignment happen without an intervening `await`, which makes each check-and-create step atomic on the event loop. Each shutdown coordinator stores the class-specific shutdown body in `_shutdown_body_task` and observes the whole body for `hassette.config.lifecycle.resource_shutdown_timeout_seconds`. This is the authoritative per-resource deadline, including hooks, cleanup, service cancellation, and child propagation. If it expires, the coordinator records `SHUTDOWN_BODY_TIMED_OUT`, invokes force-terminal handling, and, if the body remains live, records its task name in the report's `pending_tasks` (no separate cause -- the two checks share the same branch with no suspension point between them). The task separation lets the coordinator return promptly even if the body resists cancellation.

1. Every lifecycle front door first rejects `asyncio.current_task()` matching `_init_task`, `_shutdown_task`, or `_shutdown_body_task` with `LifecycleReentryError`; none creates a joiner or cancellation cycle for a re-entrant call.
2. If a shutdown task is active, initialization awaits it through `asyncio.shield()`.
3. If its report has `is_restart_safe` `False`, initialization raises `RestartRefusedError` before changing any event, status, TaskBucket, or task field.
4. If its report has `is_restart_safe` `True`, the first accepted initialization clears the prior report, clears the completed shutdown task, reopens the TaskBucket, clears `shutdown_event`, and creates `_init_task` before awaiting.
5. Other initialization callers join `_init_task` through `asyncio.shield()`.
6. Shutdown creates `_shutdown_task` once. All shutdown callers shield and await that task.
7. Repeated shutdown after completion returns `_teardown_report` without rerunning hooks.

The shutdown body first requests shutdown, cancels the active `_init_task`, and observes it for `hassette.config.lifecycle.resource_shutdown_timeout_seconds`. Only then does it run shutdown hooks. If initialization remains pending, the body records `INITIALIZATION_TASK_PENDING`, proceeds with best-effort teardown, and can never return a report with `is_restart_safe` `True`.

Before joining or creating lifecycle work, every public front door checks whether `asyncio.current_task()` is `_init_task`, `_shutdown_task`, or `_shutdown_body_task`. If so, it raises `LifecycleReentryError` without joining or cancelling a coordinator, setting shutdown state, or creating another task. Re-entrant lifecycle orchestration from initialization and shutdown hooks is unsupported; a hook that cannot continue should raise or return and let its lifecycle owner decide recovery.

This detection is limited to a resource re-entering its own active coordinator or body. Cross-resource lifecycle cycles -- a child's hook calling into its parent's lifecycle, or two resources awaiting each other -- are not detected here and rely on the whole-body shutdown timeout to eventually force-terminate.

Attempt bodies return evidence; the coordinator is the only ordinary path that stores the final report. Before storing, it merges the body's result with any force-terminal evidence already present. This prevents a late body completion from replacing a restart-unsafe report with a safe one.

If force-terminal cancels `_shutdown_task`, the coordinator catches that cancellation only when `_teardown_report` already contains `FORCED_TERMINAL`. It cancels the retained body task and returns the stored report normally, so every joined caller receives a report with `is_restart_safe` `False` rather than `CancelledError`. Coordinator cancellation without pre-recorded force evidence remains an error and is not converted to success.

Both coordinator and body tasks install lifecycle-owned done callbacks that retrieve every exception. These callbacks only log: a body or coordinator task that finishes with an unhandled exception is logged with resource, operation, and task-name context via `resource.logger.exception(...)`, but the callback never mutates `_teardown_report` and never clears `_shutdown_body_task` -- the body task reference simply stays pointed at the last completed body task until the next shutdown attempt overwrites it. If all external joiners cancel, these callbacks still prevent an unretrieved task exception from surfacing as an "exception was never retrieved" warning with no other observer.

`start()` performs the same synchronous re-entry and refusal checks before spawning its initialize joiner. It no longer resets shutdown state. `restart()` is subject to the same re-entry guard, then awaits the report, requires `is_restart_safe` `True`, and calls the coordinated `initialize()` path. The direct initialize check remains mandatory because callers can bypass `restart()`.

The existing mutable `initializing`, `shutting_down`, and `shutdown_completed` flags stop controlling lifecycle admission. Preserve their useful read behavior as properties derived from coordinator tasks and report safety, then migrate internal assignments and test reset helpers. This removes three values that can drift without imposing a documented public break on read-only diagnostics.

The blind-spot probe refuted a shutdown-only coordinator. Today a direct `await initialize()` is not stored in `_init_task`, so it can resume after teardown and overlap a later incarnation. Making `_init_task` own every initialization attempt closes that race without a generation model or general lock.

### Evidence collection

Each shutdown layer returns evidence instead of logging and discarding it:

- `run_hooks(..., continue_on_error=True)` returns the exceptions it handled. Initialization behavior remains raise-on-first-error.
- `TaskBucket` is sealed after shutdown hooks and before task cancellation. A sealed `spawn()` closes an unsubmitted coroutine when possible and raises `RuntimeError` with the bucket identity. A sealed task-factory `add()` cancels the already-created task, installs exception consumption, and raises the same error so rejected work cannot produce an unawaited-coroutine or unobserved-task warning. A clean accepted initialization reopens the bucket.
- Sealing, cancellation, and final TaskBucket inspection form a first-class shutdown stage before subclass cleanup. `TaskBucket.cancel_all()` returns a deterministic tuple of task names still pending after its bounded wait, and the sealed bucket exposes a synchronous pending-name snapshot. The shutdown coordinator reads that snapshot after normal completion and again whenever the whole-body deadline or force-terminal handling interrupts the stage, so enclosing cancellation cannot erase the names required by FR#11.
- Base `Resource.cleanup()` no longer owns TaskBucket cancellation; it is lifecycle cleanup for subclass-owned resources only. Existing overrides may continue to call `super().cleanup()`, but task evidence is collected exactly once by the shutdown body. Cleanup reports timeout or failure. The initialization task is cancelled and observed separately; a still-pending initializer adds `INITIALIZATION_TASK_PENDING`.
- `Service._shutdown_body()` cancels `_serve_task` and observes it with `asyncio.wait()`. A task still pending at the deadline adds `SERVE_TASK_PENDING`; shutdown does not wait indefinitely for cancellation acknowledgement.
- `_shutdown_children()` gathers child reports. A raised exception adds `CHILD_SHUTDOWN_FAILED`; a timeout force-finalizes unfinished children and adds `CHILD_SHUTDOWN_TIMED_OUT`.
- `_on_children_stopped()` runs only when every child report has `is_restart_safe` `True`, preserving the current safe-only hook contract.
- Failure to emit a terminal status event is logged but does not by itself imply that owned work survived, so it does not change teardown eligibility.

The shutdown attempt starts with a safe report and combines each stage's immutable evidence. It stores the final report before returning. If the attempt is cancelled by force-terminal or root timeout, the force path stores restart-unsafe evidence first, so later callers never see an absent or safe report.

### Force-terminal and root timeout

`Resource._force_terminal()` remains an exit-oriented fallback. It now records `FORCED_TERMINAL` before cancelling the initialization task, shutdown coordinator, TaskBucket work, service task, or descendants. Cancelling the coordinator triggers the report-return behavior above; it does not leak cancellation to joined callers. The method may still write `STOPPED` directly to finish lifecycle bookkeeping, but that status cannot authorize restart.

Force-terminal leaves an already completed restart-safe resource unchanged. For an active or incomplete resource it merges causes monotonically and recurses. A later task completion cannot overwrite its restart-unsafe report with a safe one.

Hassette supplies a root-specific `_shutdown_body()` that runs dependency-wave teardown through the same resource-owned shutdown attempt. Its total timeout adds both `TOTAL_TIMEOUT` and `FORCED_TERMINAL` to the root report before force-finalizing unfinished descendants, then executes the existing `handle_stop()` and event-stream closing fallback. The public shutdown front door and outer coordinator alone store and return the merged report, so neither the root body nor a cancellation-resistant inner stage can recursively enter public shutdown or later overwrite timeout evidence. This does not add a global draining gate for unrelated admission paths.

### ServiceWatcher refusal

Add one refusal handler in `ServiceWatcher` and catch `RestartRefusedError` before the generic exception branch in both `execute_restart()` and `cooldown_and_retry()`.

The handler:

1. Records the fatal reason synchronously, following the existing permanent-exhaustion race fix.
2. Calls `request_shutdown()` directly before event dispatch, so recovery control flow does not depend on telemetry delivery.
3. Builds and best-effort sends one `CRASHED` event whose existing exception fields describe `RestartRefusedError`; no payload or frontend schema changes are needed. Dispatch failure is logged and does not undo the shutdown request.
4. Keeps the `_restarting` guard until the fatal reason, shutdown request, and event attempt are complete.
5. Uses `Hassette.fatal_shutdown_reason` as the process-latched admission gate after `_restarting` is released. `restart_service()`, `execute_restart()`, and `cooldown_and_retry()` return before any retry, cooldown continuation, or `restart()` call whenever a fatal reason exists or root shutdown is requested. The same checks run immediately before each `restart()` call, closing delayed-task races without a second watcher state machine.
6. Returns without scheduling another retry, cooldown, or initialization. The existing `shutdown_if_crashed()` event handler remains valid for other crash events but is not the refusal control path.

Clean shutdown never enters this branch. Existing `RestartSpec`, budget recording, exponential backoff, cooldown limits, readiness checks, and budget reset behavior remain unchanged.

### Public contract

The repository probe confirmed that changing lifecycle `shutdown()` from `None` to `TeardownReport` is additive for current production callers: they await and discard the existing return value. Hassette's override and tests must update their annotations and aggregation behavior.

The behavior changes are intentional: direct initialization after a teardown with `is_restart_safe` `False` raises `RestartRefusedError`, and any self-joining or self-cancelling lifecycle front door invoked from an active initialization coordinator, shutdown coordinator, or shutdown body raises `LifecycleReentryError`. App authors do not override the final lifecycle orchestration methods, so their hook signatures remain unchanged.

## Implementation Preferences

- Use a frozen, slotted dataclass and `StrEnum`; do not add Pydantic models for internal lifecycle evidence.
- Keep aggregation and admission decisions in module-level functions under `hassette.resources`, matching the existing lifecycle plumbing convention and keeping names out of `App`'s public method list.
- Export teardown data types and typed errors only. Coordinator creation, joining, body invocation, and TaskBucket snapshot helpers remain internal framework plumbing.
- Use pure report merge functions and deterministic tuples rather than a mutable report builder.
- Use `asyncio.shield()` only around joins to resource-owned lifecycle tasks. Do not shield ordinary user work from shutdown.
- Use bounded `asyncio.wait()` when the target may resist cancellation.
- Reuse `RestartRefusedError` as the only watcher control-flow signal. Generic restart exceptions retain their current handling.
- Reuse `CRASHED`, existing exception fields, fatal-reason storage, and root shutdown signaling. Do not add a resource status or telemetry schema.
- Use event gates and explicit entered signals in concurrency tests. Do not use `sleep(0)` as proof that a task reached a race boundary.

## Replacement Targets

- **`run_hooks()` evidence loss:** Replace log-only shutdown error handling in `src/hassette/resources/operations.py` with a returned immutable error tuple. Remove the old implicit-success behavior.
- **TaskBucket pending-work evidence loss:** Replace `TaskBucket.cancel_all() -> None` in `src/hassette/task_bucket/task_bucket.py` with pending-task names plus sealing. Do not retain a parallel log-only path.
- **TaskBucket cancellation hidden inside cleanup:** Move seal/cancel/final-snapshot ownership from base `Resource.cleanup()` into one first-class shutdown-body stage so an enclosing timeout can still inspect the sealed bucket directly.
- **Child result compression:** Replace `_shutdown_children() -> bool` in `src/hassette/resources/base.py` and `src/hassette/core/core.py` with report aggregation. Remove boolean admission decisions.
- **Distributed lifecycle flags:** Replace mutable `initializing`, `shutting_down`, and `shutdown_completed` admission guards with resource-owned attempt tasks and report-derived read properties.
- **Unconditional restart:** Replace `restart()`'s shutdown-then-initialize sequence with report validation before initialization.
- **Service timeout treated as completion:** Replace `wait_for()` plus warning-only handling in `Service._shutdown_body()` with bounded observation and `SERVE_TASK_PENDING` evidence.
- **Force-terminal treated as safe:** Keep cancellation and terminal-status fallback, but replace its safe-completion meaning with a restart-unsafe report recorded first.
- **Watcher generic catch:** Add typed refusal handling before the generic restart exception branches; do not preserve logging-only refusal behavior.

## Convention Examples

### Immutable lifecycle payload

**Source:** `src/hassette/events/hassette.py:24-46`

```python
@dataclass(slots=True, frozen=True)
class ServiceStatusPayload:
    resource_name: str
    role: ResourceRole
    status: ResourceStatus
    previous_status: ResourceStatus | None = None
```

Use the same frozen, slotted shape for teardown evidence.

### Module-level lifecycle operation

**Source:** `src/hassette/resources/operations.py:63-67`

```python
async def restart(resource: "Resource") -> None:
    resource.logger.debug("Restarting '%s' %s", resource.class_name, resource.role)
    await resource.shutdown()
    await resource.initialize()
```

Extend this module-level pattern rather than adding app-visible framework methods.

### Bounded cancellation evidence

**Source:** `src/hassette/task_bucket/task_bucket.py:323-350`

```python
done, pending = await asyncio.wait(tasks, timeout=self.config_cancel_timeout)
for task in pending:
    self.logger.warning(
        "[%s] task %s refused to die within %.1fs",
        self.unique_name,
        task.get_name(),
        self.config_cancel_timeout,
    )
```

Return the pending names to lifecycle aggregation instead of discarding them after logging.

### Race-safe fatal escalation

**Source:** `src/hassette/core/service_watcher.py:202-220`

```python
self.hassette.record_fatal_reason(
    f"{role} '{name}' restart budget exhausted (PERMANENT)"
)
crashed_event = self.emit_service_status_event(
    name=name,
    role=role,
    status=ResourceStatus.CRASHED,
    previous_status=ResourceStatus.FAILED,
    source_payload=status_payload,
)
await self.hassette.send_event(crashed_event)
```

Record refusal before dispatch for the same reason: event handlers run asynchronously.
Request root shutdown at this decision site before best-effort event delivery; telemetry must not be the only fatal control path.

### Event-gated lifecycle fixture

**Source:** `tests/unit/resources/lifecycle/conftest.py:35-39`

```python
class HangingChild(Resource):
    async def on_shutdown(self) -> None:
        await asyncio.Event().wait()
```

New race tests should add an entered event and a release event so assertions run only after the target coroutine reaches the intended boundary.

## Alternatives Considered

### Check booleans in `restart()`

Rejected. A check in `restart()` misses `start()` and direct `initialize()`, keeps concurrent shutdown's ambiguous early return, and cannot recover errors discarded by hooks, TaskBucket, and child aggregation.

### Share only the shutdown task

Rejected by the blind-spot probe. Direct `await initialize()` is not currently tracked by `_init_task`; it can survive shutdown and resume into a later incarnation. Both lifecycle directions need an owned attempt task.

### Full generation-scoped lifecycle controller

Rejected for this issue. It would model ownership more completely but expands into app replacement, registrations, sync threads, and stale-callback fencing. Paired attempt tasks close the reproduced async race with less state and fewer migration seams.

### Process-only recovery for every service failure

Rejected as the default. It would discard working in-process backoff and restart behavior for ordinary clean failures. Process recovery is reserved for the case where shutdown cannot prove safety.

### Fresh service object after refusal

Rejected. A new object in the same process does not isolate it from surviving tasks, subscriptions, or shared capabilities owned by the old object.

## Test Strategy

Follow the repository's bug workflow: land deterministic failing regressions for the unsafe behavior before the implementation that makes them pass. Each timing test must signal when the target coroutine reaches its blocking point before making assertions.

### Required Test Types

- **Unit:** Required for report construction and merging, lifecycle admission, initialization/shutdown coordination, TaskBucket sealing, force-terminal classification, child aggregation, service-task observation, and root total-timeout behavior. These decisions are local but timing-sensitive.
- **Integration:** Required for `ServiceWatcher` because refusal crosses event handling, restart policy, fatal-reason recording, status events, and root shutdown signaling.
- **System:** Not required. This design does not promise process death or external-supervisor behavior. Existing system tests remain a regression gate for normal shutdown.
- **Frontend/E2E:** Not required because no web contract or rendered behavior changes.

### Existing Tests to Adapt

- `tests/unit/resources/test_run_hooks.py`: assert returned shutdown errors while preserving initialize re-raise and hook ordering.
- `tests/integration/test_task_bucket.py`: assert pending task names, sealed admission, final re-snapshot, and clean reopen.
- `tests/unit/resources/lifecycle/test_init.py`: replace mutable initialization-flag assumptions with shared attempt behavior, direct-call tracking, and explicit shutdown re-entry refusal.
- `tests/unit/resources/lifecycle/test_shutdown.py`: replace boolean guard assertions with stored report, repeated-return, child aggregation, retained shutdown-body observation, and safe report consumption.
- `tests/unit/resources/lifecycle/test_force_terminal.py`: assert force-terminal records restart-unsafe evidence before cancellation and leaves safe completed children unchanged.
- `tests/unit/resources/lifecycle/test_total_timeout.py`: update the root helper to use the common coordinator and assert total-timeout causes plus stream cleanup.
- `tests/unit/resources/test_service_lifecycle.py`: add bounded observation of cooperative and cancellation-resistant service tasks.
- `tests/unit/resources/test_shutdown_edge_cases.py`: update cleanup timeout/error and repeated shutdown expectations.
- `tests/unit/resources/test_service_edge_cases.py`: replace warning-only service timeout expectations with report assertions.
- `tests/unit/resources/test_add_child_and_restart.py`: preserve the clean restart round trip and add typed refusal coverage.
- `tests/integration/test_lifecycle_propagation.py`: remove direct completion-state mutation and use a fresh resource for each lifecycle sequence while preserving once-only cleanup behavior.
- `tests/unit/core/test_core_coverage.py`: update Hassette shutdown return and completion assertions.
- `tests/unit/core/test_service_watcher_coverage.py`: cover typed refusal in the ordinary backoff executor.
- `tests/unit/core/test_service_watcher_exhausted.py`: preserve existing permanent, transient, and temporary exhaustion behavior.
- `tests/unit/core/test_fatal_shutdown.py`: preserve fatal-reason-before-shutdown ordering and prove event-dispatch failure cannot prevent the direct shutdown request.
- `tests/integration/test_service_watcher.py`: exercise real watcher refusal from both backoff and cooldown paths and preserve clean recovery behavior.

### New Test Coverage

- Report factories, derived state, deterministic merging, and monotonic cause preservation. Unit, FR#1-FR#3.
- Event-gated direct initialization concurrent with shutdown. Unit, FR#4-FR#7.
- Initialize, start, restart, and shutdown calls from active initialization and shutdown hooks raise `LifecycleReentryError` without self-join, self-cancellation, or a created lifecycle attempt. Unit, FR#16.
- Two shutdown callers where one awaiter is cancelled. Unit, FR#4.
- Two restart callers after safe and restart-unsafe teardown. Unit, FR#4, FR#5, FR#7, FR#9.
- Child timeout followed by restart, start, and direct initialize refusal. Unit, FR#3, FR#7, FR#10.
- Child exception and child-returned restart-unsafe report while siblings complete. Unit, FR#2, FR#3.
- Hook error, cancellation-resistant hook, cleanup error, cleanup timeout, pending initialization, and pending TaskBucket work. Unit, FR#2, FR#3, FR#11.
- Cancellation-resistant shutdown body remains retained, named in the report, and exception-observed after every external joiner leaves. Unit, FR#17.
- Task creation attempted after sealing through both `spawn()` and the event-loop task factory. Unit/integration, FR#11.
- Cancellation-resistant `serve()` observed without cancelling the test's restart task; the old task is released in `finally`. Unit, FR#2, FR#3.
- `RestartRefusedError` content and report identity. Unit, FR#8, FR#14.
- Refusal after ordinary backoff and after transient cooldown, including failed `CRASHED` event dispatch with root shutdown still requested and a duplicate event after handler completion suppressed by the fatal-reason latch. Integration, FR#12.
- Root total timeout with an active child attempt and event-stream fallback. Unit, FR#13.

Do not assert log text as the primary proof. Assert returned reports, task identity, hook counts, emitted events, fatal reason, and shutdown-event state. Logs remain supporting observability.

### Tests to Remove

No behavior tests are removed. Tests whose names or setup encode mutable lifecycle flags are rewritten around the report and coordinator rather than kept as compatibility tests for obsolete control state.

## Documentation Updates

- `docs/pages/core-concepts/internals/lifecycle.md`: explain that `STOPPED` is lifecycle phase, document shutdown reports, re-entry refusal, restart refusal, and the host-owned process-recovery limitation.
- `CLAUDE.md`: add the teardown report and paired lifecycle-attempt ownership to the Resource hierarchy description so future changes preserve the invariant.
- Do not edit `CHANGELOG.md`; release-please will derive the changelog from the eventual conventional commit.

The implementation PR must run the repository's persona and accuracy reviews for the changed lifecycle documentation before shipping.

## Impact

### Changed Files

Shared and production code:

- **Create `src/hassette/resources/teardown.py`:** define restart safety, teardown causes, immutable report, and pure aggregation helpers.
- **Modify `src/hassette/exceptions.py`:** add `RestartRefusedError` with resource identity and report plus `LifecycleReentryError` for lifecycle calls made from their own coordinator or body.
- **Modify `src/hassette/resources/mixins.py`:** add shutdown coordinator, retained body, and report ownership; make `_init_task` authoritative for every initializer; and derive lifecycle diagnostics from tasks/report.
- **Modify `src/hassette/resources/lifecycle.py`:** add internal create/join/admission helpers, observe coordinator/body completion, and stop `start()` from resetting shutdown evidence.
- **Modify `src/hassette/resources/operations.py`:** return hook evidence and require `is_restart_safe` `True` in `restart()`.
- **Modify `src/hassette/resources/base.py`:** split final public lifecycle front doors from unsafe internal bodies; aggregate cleanup, task, and child evidence; return reports; make TaskBucket cancellation a first-class stage; and classify force-terminal.
- **Modify `src/hassette/resources/service.py`:** provide service-specific internal lifecycle bodies and bounded service-task observation without overriding a public front door recursively.
- **Modify `src/hassette/resources/__init__.py`:** export teardown data types only; do not export new coordinator helpers.
- **Modify `src/hassette/task_bucket/task_bucket.py`:** add sealed admission and return pending task names from cancellation.
- **Modify `src/hassette/core/core.py`:** provide the root shutdown body and timeout fallback without recursively entering a public front door, aggregate wave reports, and return the root report.
- **Modify `src/hassette/core/service_watcher.py`:** route typed refusal from backoff and cooldown through one fatal path.
- **Modify `src/hassette/test_utils/reset.py`:** keep reset limited to a shutdown request that has not started teardown; reject a root or descendant with an active shutdown task or any teardown report, and never clear coordinator fields.

Tests and fixtures:

- **Create `tests/unit/resources/test_teardown.py`:** cover derived restart safety, aggregation, and refusal formatting.
- **Modify `tests/unit/resources/lifecycle/conftest.py`:** add entered/release-gated child and service fixtures.
- **Modify `tests/unit/resources/lifecycle/test_init.py`:** cover initialization ownership, admission, and initialization-hook re-entry refusal.
- **Modify `tests/unit/resources/lifecycle/test_shutdown.py`:** cover joined shutdown, retained body observation, shutdown-hook re-entry refusal, report reuse, child aggregation, and clean restart eligibility.
- **Modify `tests/unit/resources/lifecycle/test_force_terminal.py`:** cover restart-unsafe force-terminal behavior.
- **Modify `tests/unit/resources/lifecycle/test_total_timeout.py`:** cover root report and fallback ordering.
- **Modify `tests/unit/resources/test_run_hooks.py`:** cover returned hook evidence.
- **Modify `tests/unit/resources/test_add_child_and_restart.py`:** cover clean restart and refusal.
- **Modify `tests/unit/resources/test_service_lifecycle.py`:** cover service-task completion evidence.
- **Modify `tests/unit/resources/test_shutdown_edge_cases.py`:** cover cleanup evidence and repeated shutdown.
- **Modify `tests/unit/resources/test_service_edge_cases.py`:** cover service timeout classification.
- **Modify `tests/integration/test_task_bucket.py`:** cover sealing and pending-task results.
- **Modify `tests/integration/test_lifecycle_propagation.py`:** use fresh resources instead of clearing completion state while preserving once-only hooks.
- **Modify `tests/unit/core/test_core_coverage.py`:** cover Hassette report return paths.
- **Modify `tests/unit/core/test_service_watcher_coverage.py`:** cover ordinary refusal routing.
- **Modify `tests/unit/core/test_service_watcher_exhausted.py`:** preserve exhaustion semantics.
- **Modify `tests/unit/core/test_fatal_shutdown.py`:** cover refusal fatal ordering and event-independent shutdown signaling.
- **Modify `tests/integration/test_service_watcher.py`:** cover backoff and cooldown refusal end to end.
- **Modify `tests/unit/core/conftest.py`:** migrate watcher lifecycle fixture reset from mutable completion flags.

Documentation:

- **Modify `docs/pages/core-concepts/internals/lifecycle.md`:** document teardown outcomes and restart refusal.
- **Modify `CLAUDE.md`:** record the lifecycle ownership invariant for maintainers.

<!-- Gap check 2026-08-27: 3 gaps included — mutable `_init_task`/flag assertions
(`tests/unit/resources/test_lifecycle_transitions.py:376`) → T03 Focus; constructor-bypassing lifecycle field setup
(`tests/unit/core/test_logging_service.py:48`) → T03 Focus; stale public TaskBucket cancellation description
(`docs/pages/core-concepts/apps/task-bucket.md:93`) → T08 Focus. -->

### Behavioral Invariants

- Clean Resource and Service shutdown remains bounded by existing lifecycle configuration.
- Every lifecycle coordinator and retained shutdown body has framework-owned exception observation even when all callers cancel their joins.
- A process-latched fatal reason or root shutdown request prevents all later ServiceWatcher recovery entry points from calling `restart()`.
- Clean same-instance restart remains available and follows existing `RestartSpec` policy.
- Hook order stays `before_shutdown`, service cancellation where applicable, `on_shutdown`, `after_shutdown`, cleanup, children, then terminal handling.
- Children still shut down in reverse insertion order; Hassette still uses reverse dependency waves.
- `_on_children_stopped()` remains clean-path only.
- Root event streams still close on ordinary shutdown and total-timeout fallback.
- Existing lifecycle status values and status event schemas do not change.
- Fatal and non-retryable exception routing unrelated to teardown refusal does not change.
- AppLifecycleService continues to ignore the returned report until #1689; this PR makes no claim that app replacement is safe after a restart-unsafe teardown.
- No configuration key, CLI behavior, database schema, or frontend contract changes.

### Blast Radius

Every `Resource`, `Service`, and `App` instance inherits the coordinator and report-returning shutdown contract. App object shutdown becomes observable, and direct reinitialization of the same App object is refused after a teardown with `is_restart_safe` `False`, but AppLifecycleService replacement policy remains unchanged.

Framework services depend on clean same-instance restart, so regressions in report aggregation or report consumption could turn recoverable failures into process shutdown. ServiceWatcher tests and existing restart-budget tests are the main protection.

Test harnesses must construct fresh resources after a completed teardown. `reset_hassette_lifecycle()` may clear an unconsumed root shutdown request only before any shutdown attempt exists; it raises if the root or a descendant has an active shutdown task or teardown report. External code that only awaits and ignores `shutdown()` remains source-compatible; code that directly mutates internal lifecycle flags is intentionally unsupported.

## Open Questions

None. Sync-thread ownership, app replacement, root-wide admission, frontend telemetry, and enforced process death are accepted exclusions rather than unresolved design decisions.

## Addendum

### 2026-08-30: Wave-level shutdown timeout is a deliberate, accepted trade-off

Edge Case (line 108) covers a wave timing out *after* some children have already fully
completed, but does not name the narrower case: `_shutdown_children()` (and `Hassette`'s own
wave-based override in `core.py`) wraps an entire wave's `asyncio.gather()` in one shared
`asyncio.timeout()`. There is no per-child timeout and no salvage path for a child that is
milliseconds from finishing on its own when the wave deadline fires — on timeout, every child in
that wave without an already-recorded `teardown_report` is force-terminated, including ones that
would have completed cleanly within the same event-loop tick.

This is an accepted trade-off, not a gap to close: co-scheduled siblings sharing one wave-level
timeout is a deliberate simplification. Correctly distinguishing "about to finish" from "actually
hung" would require per-task completion checking (e.g. `asyncio.wait(child_tasks, timeout=...,
return_when=ALL_COMPLETED)` plus a done-check race against `force_terminal()`) — real
implementation complexity for a narrow edge case whose worst outcome is a technically-fine
child's teardown evidence being labeled force-terminated instead of gracefully-completed, not a
correctness or data-loss risk. Revisit only if this narrow mislabeling actually causes a concrete
observed problem (a flaky test, a confusing production report) — that gives a real trigger to
design the fix against, rather than guessing at the right shape now.

### 2026-08-30: A bare teardown timeout also forecloses transient backoff/cooldown recovery

Key Constraints (line 159, "No public or test-only reset may clear a report with
`is_restart_safe` `False`") is written for the case this design targets: a coroutine that
provably ignores cancellation. `RestartSpec`/`RestartBudget` already model transient-vs-permanent
failure for ordinary `FAILED`/`CRASHED` service-loop failures (retry with backoff, exhaust-and-
shutdown, mark-dead-but-recoverable). Teardown/shutdown timeout is a second failure axis this
design introduces with no equivalent distinction: any `SHUTDOWN_BODY_TIMED_OUT`,
`CLEANUP_TIMED_OUT`, or `TASKS_PENDING` cause makes `is_restart_safe` permanently `False`, with no
in-process reset path, regardless of whether the timeout came from a genuinely-wedged coroutine or
from ordinary budget pressure (a GC pause, a co-located app's CPU spike, or — before the 2026-08-30
budget-accounting fix above — one stage structurally starving another). `handle_restart_refused()`
escalates straight to fatal process shutdown on the *first* `RestartRefusedError`, with no budget,
retry, or cooldown of its own.

This is an acknowledged gap, not a decision reversal: a first-strike/second-strike distinction
(one isolated timeout gets standard `RestartSpec` transient handling; only a repeated or
confirmed-resistant one escalates to permanent refusal) would be a real architecture change to the
restart-safety model, and this design already explicitly rejects a full generation-scoped
lifecycle controller as overkill (see Alternatives Considered). Recorded here so a future incident
where a transient timeout wedges a resource permanently isn't a surprise.
