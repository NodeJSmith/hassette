# Design: Scope restart-refusal escalation to the failing service instead of the whole process

**Date:** 2026-08-31
**Status:** archived
**Mode:** sketch

## Problem

`ServiceWatcher.handle_restart_refused()` (`src/hassette/core/service_watcher.py:229-259`) treats every `RestartRefusedError` identically: record a fatal reason and request root-wide shutdown, killing every other service and app in the process. `RestartRefusedError` fires whenever a resource's `TeardownReport.is_restart_safe` is `False` — which includes a plain timeout overrun (`CLEANUP_TIMED_OUT`, `TASKS_PENDING`, `SERVE_TASK_PENDING`, `SHUTDOWN_BODY_TIMED_OUT`), not just a genuinely dangerous failure (a hook raising, `CHILD_RESTART_UNSAFE`, `FORCED_TERMINAL`). Production timeout defaults are tight (`resource_shutdown_timeout_seconds` defaults to `app_shutdown_timeout_seconds`, `task_cancellation_timeout_seconds=5`), and a resource-constrained home-automation host (Raspberry Pi, momentary network latency to Home Assistant) can trip these routinely without anything actually being broken. The original design (`design/specs/105-teardown-restart-safety`) explicitly rejected "process-only recovery for every service failure" as the default — but the shipped mechanism doesn't distinguish "shutdown proved genuinely dangerous" from "shutdown was a few seconds slower than budget."

## Goals

- Stop a single service's mere-timeout teardown from taking down the entire framework and every unrelated app with it.
- Do this without weakening the existing safety guarantee: a resource that might still have a background task alive must never be treated as safe to leave running unmonitored.
- Stay within what the current architecture actually supports — do not attempt to reconstruct or auto-restart the affected service in-process (see Non-Goals).

## Non-Goals

- **Automatic in-process recovery of the affected service.** `restart()` cannot get a second attempt at the same resource object — `TeardownReport` is cached once and immutable, and the original design explicitly disallows any reset path ("no public or test-only reset may clear UNSAFE"). Actually reconstructing a fresh instance would require a generic per-service factory mechanism `ServiceWatcher` doesn't have today (most core services need extra constructor kwargs beyond `hassette`/`parent` — e.g. `SchedulerService` needs `executor`, `LoggingService` needs `stream_handler`, `AppLifecycleService` needs `registry`), plus a way to remove/replace a child in `Resource.children` without violating the "at most one instance per type" invariant. This is filed separately as [#1767](https://github.com/NodeJSmith/hassette/issues/1767) and deliberately out of scope here.
- Changing behavior for causes that indicate an actual failure (a hook raised, cleanup raised, a child was force-terminated, the coordinator itself failed) — those keep escalating to root shutdown exactly as today.
- Changing behavior for services opted out of the new degrade path — `BusService`, `SchedulerService`, `SyncExecutorService` (all `PERMANENT`-restart-type), and `WebsocketService` and `WebApiService` (both `TRANSIENT`, but excluded anyway — see Approach) — see Approach. `WebApiService` was added to this list during ship-time challenge: it meets the same "no path back for a human to notice or intervene" criterion already applied to `WebsocketService` (it's the framework's sole dashboard/REST/health interface), so the same exclusion applies for the same reason.

## Functional Requirements

- **FR#1** `TeardownReport` can report whether every cause it recorded is one of `TASKS_PENDING`, `SERVE_TASK_PENDING`, `SHUTDOWN_BODY_TIMED_OUT` (a "timeout-only" refusal) versus containing any other cause. `CLEANUP_TIMED_OUT` is deliberately excluded even though it sounds recoverable: FR#2's quiescence check has no way to observe `cleanup()`'s actual completion (it only inspects `task_bucket`/`_shutdown_body_task`), so a `CLEANUP_TIMED_OUT` refusal cannot be genuinely confirmed quiescent — it must always escalate.
- **FR#2** A resource's actual current quiescence — whether its `task_bucket` has any pending tasks and whether its shutdown-body task (if any) has finished — can be checked at any point after teardown, not just at the moment the report was generated.
- **FR#3** When a `TRANSIENT`- or `TEMPORARY`-restart-type service's restart is refused with a timeout-only report, `ServiceWatcher` waits up to half of `resource_shutdown_timeout_seconds` for that resource to become confirmed-quiescent before deciding how to respond, instead of escalating immediately.
- **FR#4** If confirmed-quiescent within that wait, `ServiceWatcher` marks only that service `EXHAUSTED_DEAD` (existing terminal status) and emits the corresponding status event — the rest of the framework, including other services and already-running apps, is left untouched. No root shutdown occurs.
- **FR#5** If the wait times out without confirming quiescence, or the refusal is not timeout-only, or the service has opted out of the degrade path (`restart_spec.degrade_on_confirmed_quiescent_refusal` is `False` — `PERMANENT` services and `WebsocketService`), `ServiceWatcher` falls back to today's unchanged behavior: record a fatal reason and request root-wide shutdown.
- **FR#6** `docs/pages/core-concepts/internals/lifecycle.md` describes the new decision flow (state diagram and the "Restart refusal" prose) so it no longer says `ServiceWatcher` treats every refusal identically.

## Acceptance Criteria

- **AC#1** A unit test on `TeardownReport` proves a report containing only timeout-only causes reports the new classification as `True`, and a report that also contains a non-timeout cause (e.g. `CLEANUP_FAILED`) reports `False`. Maps to FR#1.
- **AC#2** A unit test proves the new quiescence check returns `False` while a tracked task is still pending and `True` once it completes, for both the task-bucket case and the shutdown-body-task case. Maps to FR#2.
- **AC#3** An integration test proves a `TRANSIENT` service whose tracked task never finishes within the wait bound still results in root-wide shutdown (`fatal_shutdown_reason` set, `shutdown_event` set) — unchanged from today. Maps to FR#3, FR#5.
- **AC#4** An integration test proves a `TRANSIENT` service whose tracked task finishes shortly after the timeout (confirmed within the bound) ends with only that service at `EXHAUSTED_DEAD`, a sibling service still `RUNNING`, and no fatal reason recorded. Maps to FR#3, FR#4.
- **AC#5** An integration test proves a `PERMANENT`-restart-type service's timeout-only refusal still escalates to root shutdown even when its task is confirmed dead within the bound. Maps to FR#5.
- **AC#6** `prek -a` and the affected unit/integration suites (`tests/unit/resources/test_teardown.py`, `tests/unit/resources/lifecycle/test_shutdown.py`, the new `tests/integration/test_service_watcher_refusal_scoping.py`) pass.
- **AC#7** A unit or integration test proves `WebsocketService.restart_spec.degrade_on_confirmed_quiescent_refusal` is `False`, and that a timeout-only refusal for it still escalates to root shutdown even when confirmed dead within the bound — same outcome as AC#5, for the same reason (framework-critical service), via the same opt-out mechanism. Maps to FR#5.

## Approach

### Classify the refusal (`src/hassette/resources/teardown.py`)

Add a module-level `TIMEOUT_ONLY_CAUSES: frozenset[TeardownCause]` constant listing the three causes that mean "might just need more time" *and* are actually verifiable by the FR#2 quiescence check (`TASKS_PENDING`, `SERVE_TASK_PENDING`, `SHUTDOWN_BODY_TIMED_OUT`), and a `TeardownReport.is_timeout_only_refusal` property: `True` when `causes` is non-empty and every cause is in that set, `False` otherwise (including the empty-causes/restart-safe case — there's nothing to classify if nothing went wrong). `CLEANUP_TIMED_OUT` is excluded despite sounding recoverable: the FR#2 quiescence check only inspects `task_bucket.pending_task_names()` and `_shutdown_body_task`, neither of which tracks `cleanup()` — by the time a refusal is raised, `cleanup()` has already been cancelled at its timeout boundary and the task bucket is empty, so there is nothing for the check to actually confirm. Treating it as timeout-only would make the "confirmed quiescent" outcome fire almost instantly regardless of whether the work `cleanup()` was doing (e.g. closing DB connections) genuinely finished — the opposite of what "confirm, don't assume" is supposed to guarantee. Every other `TeardownCause` (`CLEANUP_TIMED_OUT`, `SHUTDOWN_HOOK_FAILED`, `SHUTDOWN_BODY_FAILED`, `CLEANUP_FAILED`, `INITIALIZATION_TASK_PENDING`, `CHILD_SHUTDOWN_FAILED`, `CHILD_SHUTDOWN_TIMED_OUT`, `CHILD_RESTART_UNSAFE`, `FORCED_TERMINAL`, `TOTAL_TIMEOUT`, `COORDINATOR_FAILED`) represents an actual failure, an unverifiable timeout, or a child's own unsafe report, not "still finishing up and checkable" — any of those present means immediate escalation, same as today.

This is deliberately independent from actually checking whether anything is currently running (below) — a report can be timeout-only in shape while the resource has, in the meantime, actually become fully quiescent or still be running. The two checks answer different questions: "was the *reason* for refusal something that resolves with time?" vs. "*has* it resolved?"

### Confirm quiescence (`src/hassette/resources/lifecycle.py`)

Add a module-level function alongside the other resource-taking lifecycle helpers (`mark_ready`, `handle_failed`, etc.):

```python
def is_teardown_confirmed_quiescent(resource: _LifecycleHostP) -> bool:
    """Return True if nothing tracked from the resource's last teardown attempt is still running."""
    resource = typing.cast("LifecycleMixin", resource)
    body_task = resource._shutdown_body_task
    return not resource.task_bucket.pending_task_names() and (body_task is None or body_task.done())
```

This lives in `lifecycle.py` rather than being inlined in `ServiceWatcher` because it touches `_shutdown_body_task`, a `LifecycleMixin`-private attribute — `lifecycle.py` already owns this kind of resource-internals access. `reject_lifecycle_reentry()` (`lifecycle.py:448`) is the exact precedent: its public signature takes `resource: _LifecycleHostP` (the module's documented convention — see its docstring, "Functions are typed against `_LifecycleHostP`"), then casts internally via `typing.cast("LifecycleMixin", resource)` before touching `_init_task`/`_shutdown_task`/`_shutdown_body_task`. `is_teardown_confirmed_quiescent` follows the same pattern for `_shutdown_body_task`.

`task_bucket` itself needs no cast — `_LifecycleHostP` already declares it — but it does need a Protocol change. `_LifecycleHostP.task_bucket` is typed as `_TaskBucketP` (`mixins.py:80-84`), which declares only `spawn`, `cancel_all_sync`, `cancel_all`, and `reopen`; neither `pending_task_names()` nor `pending_tasks()` is on it, so calling either through this typing fails Pyright today. This change adds `pending_task_names(self) -> tuple[str, ...]: ...` to `_TaskBucketP` (see Changed Files). `pending_task_names()` — not `pending_tasks()` — is the right one to expose: it's already documented as "safe to call from a force-terminal or timeout path that must inspect the bucket without awaiting anything" (`task_bucket.py:119-126`), a synchronous names-only snapshot rather than a handle to live `asyncio.Task` objects, which is all this check needs. It reflects live state regardless: every tracked task (including `_serve_task`, spawned via `task_bucket.spawn()` — `service.py:119`) is discarded from the bucket's internal set via a done-callback the moment it actually finishes (`task_bucket.py:167`), not just at the moment a report was generated. `_shutdown_body_task` is set once and never reset to `None` (`lifecycle.py:748`), so polling `.done()` on it later is safe indefinitely.

### Wait, then decide (`src/hassette/core/service_watcher.py`)

Add two methods:

```python
_DEATH_CONFIRMATION_POLL_SECONDS = 1.0  # module-level constant, alongside SERVICE_STATUS_PATH

async def wait_for_teardown_confirmation(self, service: Service, timeout: float) -> bool:
    """Poll until the service's last teardown attempt is confirmed quiescent, or timeout elapses."""
    deadline = time.monotonic() + timeout
    while True:
        if is_teardown_confirmed_quiescent(service):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        completed = await self.shutdown_safe_sleep(min(_DEATH_CONFIRMATION_POLL_SECONDS, remaining))
        if not completed:  # shutdown requested mid-wait
            return False

async def handle_timeout_only_refusal(
    self, name: str, role: object, service: Service, error: RestartRefusedError
) -> None:
    """Wait for confirmed quiescence, then degrade just this service, or escalate as before."""
    # Recorded before the wait so we can tell "this service caused the shutdown" apart from
    # "shutdown was already happening for an unrelated reason when this wait aborted."
    already_shutting_down = self.hassette.shutdown_event.is_set()
    # Half the original teardown timeout: that timeout already fired once discovering this
    # resource wouldn't die cleanly, so reusing the full value here would let a genuinely-stuck
    # resource take up to 2x as long to reach root shutdown.
    timeout = self.hassette.config.lifecycle.resource_shutdown_timeout_seconds / 2
    if await self.wait_for_teardown_confirmation(service, timeout):
        self.logger.warning(
            "%s '%s' restart refused (timeout-only: %s), confirmed no tasks still running — "
            "marking EXHAUSTED_DEAD instead of shutting down the process",
            role, name, ", ".join(error.report.causes),
        )
        dead_event = HassetteServiceEvent.from_service_status(
            resource_name=name,
            role=role,  # pyright: ignore[reportArgumentType]
            status=ResourceStatus.EXHAUSTED_DEAD,
            previous_status=service.status,
            exception=error,
        )
        await self.hassette.send_event(dead_event)
        self.set_service_status(name, role, ResourceStatus.EXHAUSTED_DEAD)
        return
    if already_shutting_down:
        self.logger.warning(
            "%s '%s' restart refused (timeout-only: %s) during an already-in-progress shutdown "
            "for an unrelated reason — skipping a redundant, misattributed CRASHED event for "
            "this service",
            role, name, ", ".join(error.report.causes),
        )
        return
    self.logger.warning(
        "%s '%s' restart refused (timeout-only: %s) but could not confirm quiescence within %.1fs — escalating",
        role, name, ", ".join(error.report.causes), timeout,
    )
    await self.handle_restart_refused(name, role, error)
```

Both existing `except RestartRefusedError as exc:` blocks (`cooldown_and_retry`, ~line 398; `execute_restart`, ~line 545) change from an unconditional `await self.handle_restart_refused(name, role, exc)` to:

```python
except RestartRefusedError as exc:
    if exc.report.is_timeout_only_refusal and spec.degrade_on_confirmed_quiescent_refusal:
        await self.handle_timeout_only_refusal(name, role, service, exc)
    else:
        await self.handle_restart_refused(name, role, exc)
```

Both call sites already have `service` and `spec` in scope, so no new parameters need to be threaded through.

**Bystander guard.** If `wait_for_teardown_confirmation()` aborts early because `hassette.shutdown_event` was already set by a different, unrelated fatal failure elsewhere, `handle_timeout_only_refusal()` must not fall through to `handle_restart_refused()` — that would dispatch a second, misleading `CRASHED` event scoped to this service, even though this service's only real issue was a plain timeout and it wasn't the actual cause. `record_fatal_reason()`'s first-wins semantics already protect the reported fatal reason string, but not the per-service `CRASHED` event semantics, so the check above (`already_shutting_down`, captured *before* the wait begins) skips the redundant escalation call entirely once shutdown is already in progress for an unrelated reason.

**`_restarting` guard window.** `execute_restart()`'s `finally: self._restarting.discard(key)` (`service_watcher.py:566-567`) only runs once `handle_timeout_only_refusal()` returns, which can now take up to the confirmation-wait bound. During that window, `restart_service()`'s existing Step 3 guard silently drops any redelivered `FAILED` event for the same service at debug level — unchanged behavior, just held open longer than before. No code change needed; noted here since the design extends how long that window stays open.

**Diagnostic payload.** The confirmed-dead event is built via `HassetteServiceEvent.from_service_status(..., exception=error)`, not `self.emit_service_status_event(...)` — `emit_service_status_event()` only pulls exception fields from an existing `ServiceStatusPayload` passed as `source_payload`, which doesn't exist here (there's no prior `HassetteServiceEvent` to extract one from, only the `RestartRefusedError` itself). `from_service_status()` accepts an `exception` directly and extracts its fields internally (`extract_exception_fields`) — the same constructor `handle_restart_refused()` already uses for its own `CRASHED` event (`service_watcher.py:248-255`). Without this, the emitted event would carry no exception/traceback at all, and the dashboard's exception-disclosure UI (`service-row.tsx`) never renders for this path — a real regression relative to today's `CRASHED` event for the same underlying `RestartRefusedError`.

**Status transition correctness.** By the time `restart()` raises `RestartRefusedError`, `resource.shutdown()` has already completed and driven the resource's status to `STOPPED` (via `handle_stop()` on the normal path, or `_force_terminal()` on the force-terminal path) — never `FAILED`. `VALID_TRANSITIONS[ResourceStatus.STOPPED]` (`mixins.py:51`) currently allows only `STARTING`, so a hardcoded `previous_status=ResourceStatus.FAILED` followed by `set_service_status(..., EXHAUSTED_DEAD)` would both misreport the real prior status and hit an invalid transition under `strict_lifecycle=True` (which `HassetteHarness` forces unconditionally — the exact harness this feature's own integration tests use). The code above reads `service.status` directly instead of assuming `FAILED`, and `VALID_TRANSITIONS[ResourceStatus.STOPPED]` gains `EXHAUSTED_DEAD` as a documented, intentional addition (see Changed Files) — a comment on the new entry should explain it's for a confirmed-quiescent timeout-only refusal, matching the existing inline-comment convention already used throughout the table (e.g. `# budget exhausted, temporary`).

### Why `PERMANENT` services and `WebsocketService` are excluded

`BusService`, `SchedulerService`, and `SyncExecutorService` use `restart_spec = CORE_PERMANENT_RESTART`. The existing exhaustion path already treats `PERMANENT` as "this is too foundational to run without" — ordinary (non-refused) budget exhaustion for a `PERMANENT` service goes to `CRASHED` + `await self.hassette.shutdown()` (`handle_exhaustion`'s `PERMANENT` branch), not a per-service degrade. Docs already describe `TRANSIENT`/`TEMPORARY` as the types where "Hassette continues running without it" is an accepted, documented outcome (`docs/pages/core-concepts/internals/lifecycle.md`); `PERMANENT` carries no such statement. Applying the new confirmed-quiescence degrade path to a `PERMANENT` service (e.g. `BusService` going `EXHAUSTED_DEAD` while everything else keeps reporting `RUNNING`) would leave the framework in a state strictly worse than a clean shutdown — every other service and app would keep "running" while doing nothing useful, since nothing can dispatch events.

That same argument applies to `WebsocketService`, even though it's `TRANSIENT` (`websocket_service.py:88-89`), not `PERMANENT` — it's the framework's sole connection to Home Assistant. If it reaches `EXHAUSTED_DEAD` via this path, Hassette runs forever with no path back to HA for the rest of the process's life (a true dead end — `EXHAUSTED_DEAD` is a member of `TERMINAL_STATUSES`), while every other service and app keeps reporting individually healthy. That's worse than today's fast crash-and-restart: it looks alive while doing nothing useful, exactly the outcome the `PERMANENT` exclusion already exists to avoid.

Because `WebsocketService` needs ordinary `TRANSIENT` semantics for everything else (budget/backoff/cooldown on normal restart failures — only this one specific decision needs PERMANENT-like treatment), reusing `restart_type` as the sole exclusion signal doesn't work; it's an orthogonal axis. `RestartSpec` gains a dedicated field instead:

```python
degrade_on_confirmed_quiescent_refusal: bool | None = None
"""Whether a timeout-only restart refusal, once confirmed quiescent, degrades just this service
to EXHAUSTED_DEAD instead of escalating to root shutdown. False for services where running the
rest of the framework without this one is worse than a clean restart.

Leave unset (``None``) to get the type-appropriate default: ``True`` for TRANSIENT/TEMPORARY,
``False`` for PERMANENT. An unset value that resolves to ``True`` emits a warning naming this
field, since a plain dataclass has no way to tell "the caller explicitly chose the default" from
"the caller never noticed this field exists" -- the exact way this field went unnoticed on
WebApiService until a ship-time challenge caught it."""
```

`__post_init__` resolves the `None` sentinel to a concrete `bool` before construction completes, so every consumer of an already-built `RestartSpec` treats it as a plain `bool`; the `None` branch only exists to distinguish "explicit default" from "never set" for the warning above. Left unset, every existing and future `TRANSIENT`/`TEMPORARY` service still gets the new resilience-improving behavior automatically, with no opt-in required and no warning (the resolved value is `True`, but it was never left implicit by a service that should have opted out). Set to `False` explicitly on `CORE_PERMANENT_RESTART` (covering `BusService`/`SchedulerService`/`SyncExecutorService` in one place) and on `WebsocketService`/`WebApiService` via the `RestartSpec.single_point_of_failure()` classmethod — a named, self-documenting constructor for "this service is the framework's sole path to some capability nothing else can substitute for," which sets this field to `False` while still taking the same `restart_type`/`budget_intensity`/`budget_period_seconds`/`startup_timeout_seconds` overrides each service already needs. The guard in the previous section reads this field directly (`spec.degrade_on_confirmed_quiescent_refusal`) rather than checking `restart_type`, which both correctly covers `WebsocketService`/`WebApiService` and reads as a direct statement of intent rather than a `restart_type` proxy.

**Known downstream degradation for the remaining `TRANSIENT`/`TEMPORARY` services left in-scope** (`DatabaseService`, `CommandExecutor`, `FileWatcherService`, `WebUiWatcherService`) — named explicitly so "smaller blast radius" is a measured claim, not an assumed one. `WebApiService` was moved to the excluded list during ship-time challenge (see Non-Goals) — it fails the same "no path back for a human to notice or intervene" test `WebsocketService` was already excluded for, so it is not listed here:
- `DatabaseService` dead: telemetry/dashboard queries degrade to 503 via the existing `db_degrades_to` pattern (`src/hassette/web/CLAUDE.md`). HA state itself lives in `StateProxy`, not here, so event handling and automations keep running.
- `CommandExecutor` dead: despite the name, it persists execution *telemetry* to SQLite (`command_executor.py:104-112`) — it doesn't execute automations itself. Losing it drops telemetry records; nothing stops running.
- `FileWatcherService`/`WebUiWatcherService` (`TEMPORARY`) are already covered by the docs' own existing statement: "losing live-reload capability does not impair automation execution."

### Docs

Update `docs/pages/core-concepts/internals/lifecycle.md`:

- State diagram (~line 79-94): add `STOPPED --> EXHAUSTED_DEAD : timeout-only refusal, confirmed quiescent (TRANSIENT/TEMPORARY)` — **from `STOPPED`, not `FAILED`**. By the time this new path fires, `restart()` has already called `resource.shutdown()`, which drives status to `STOPPED` (via `handle_stop()` or `_force_terminal()`) before `RestartRefusedError` is ever raised — the same reasoning covered in "Status transition correctness" above, and the reason `VALID_TRANSITIONS[ResourceStatus.STOPPED]` (not `[ResourceStatus.FAILED]`, which already permits it) is what gains the new entry. Place the new line near `STOPPED --> [*]`, not near the existing `FAILED --> EXHAUSTED_DEAD` lines.
- "Restart refusal" section (~line 180-198): replace "`ServiceWatcher` treats `RestartRefusedError` as a fatal outcome rather than an ordinary restart failure... It does not retry, enter cooldown, or attempt another restart for that service." with a description of the classify → wait → degrade-or-escalate flow, keeping the existing `!!! warning` about cooperative cancellation (still accurate — it explains exactly why the confirmation wait is bounded rather than indefinite).

### Test placement

`tests/integration/test_service_watcher.py` is already 1027 lines, past the 800-line ceiling in `CLAUDE.md`, and already tracked for a split in [#1721](https://github.com/NodeJSmith/hassette/issues/1721) — whose own proposed split boundary is "fatal-shutdown/refusal-escalation tests vs. restart/backoff/cooldown tests." Rather than adding more bulk to the file #1721 wants to split, put this feature's integration tests in a new `tests/integration/test_service_watcher_refusal_scoping.py` — a topic-scoped filename following the same naming convention as `test_service_watcher_exhausted.py` and `test_service_watcher_coverage.py` (both in `tests/unit/core/`, not `tests/integration/`), landing in `tests/integration/` because that's where the closely-related existing refusal-escalation scenarios already live, inside `test_service_watcher.py`. Unit tests for `TeardownReport.is_timeout_only_refusal` go in the existing `tests/unit/resources/test_teardown.py` (249 lines, room to grow); unit tests for `is_teardown_confirmed_quiescent` go in the existing `tests/unit/resources/lifecycle/test_shutdown.py`.

Follow the deterministic event-gated pattern from `CLAUDE.md`'s "Regression test patterns for this project" for the confirmation-wait tests — signal task completion via an `asyncio.Event` the test controls, not `asyncio.sleep(0)` or real-time races. For AC#4 (confirmed-within-bound), spawn a task in the fake service's `task_bucket` that the test releases (via an `asyncio.Event.set()`) shortly after the simulated teardown timeout fires, and assert `wait_for_teardown_confirmation` returns `True` once released.

## Convention Examples

- `shutdown_safe_sleep()` (`service_watcher.py:149-162`) — the shutdown-interruptible sleep pattern `wait_for_teardown_confirmation`'s polling loop reuses directly, rather than a bare `asyncio.sleep()`.
- `emit_service_status_event()` + `set_service_status()` (`service_watcher.py:164-192`, `140-147`) — the existing status-transition-and-telemetry pattern `handle_timeout_only_refusal`'s confirmed-dead branch follows, matching `handle_exhaustion`'s `TEMPORARY` branch (`service_watcher.py:319-333`).
- `reject_lifecycle_reentry()` (`lifecycle.py:448`) — the module-level, `_LifecycleHostP`-typed-then-cast pattern `is_teardown_confirmed_quiescent` follows instead of becoming a `ServiceWatcher` method reaching into another object's private attribute.

## Changed Files

- **modify** `src/hassette/resources/teardown.py` — add `TIMEOUT_ONLY_CAUSES` constant and `TeardownReport.is_timeout_only_refusal` property.
- **modify** `src/hassette/resources/mixins.py` — add `pending_task_names(self) -> tuple[str, ...]: ...` to `_TaskBucketP`, so `is_teardown_confirmed_quiescent` can call it through the `_LifecycleHostP`-typed `task_bucket` field without a Pyright error; add `ResourceStatus.EXHAUSTED_DEAD` to `VALID_TRANSITIONS[ResourceStatus.STOPPED]`, since a confirmed-quiescent timeout-only refusal transitions from `STOPPED` (the status `resource.shutdown()` always leaves a resource in, refused or not), not `FAILED`.
- **modify** `src/hassette/resources/lifecycle.py` — add `is_teardown_confirmed_quiescent(resource)`.
- **modify** `src/hassette/core/service_watcher.py` — add `wait_for_teardown_confirmation()`, `handle_timeout_only_refusal()`, `_DEATH_CONFIRMATION_POLL_SECONDS`; update the two `except RestartRefusedError` blocks in `cooldown_and_retry()` and `execute_restart()` to check `spec.degrade_on_confirmed_quiescent_refusal`.
- **modify** `src/hassette/resources/restart.py` — add `degrade_on_confirmed_quiescent_refusal: bool | None = None` to `RestartSpec`, with `__post_init__` sentinel resolution and a warning when it resolves to `True` implicitly; set `False` explicitly on `CORE_PERMANENT_RESTART`; add the `RestartSpec.single_point_of_failure()` classmethod (explicit named params, no blind `**kwargs` forwarding) as the way single-point-of-failure services opt out.
- **modify** `src/hassette/core/websocket_service.py`, `src/hassette/core/web_api_service.py` — construct `restart_spec` via `RestartSpec.single_point_of_failure()` instead of the plain constructor.
- **modify** `docs/pages/core-concepts/internals/lifecycle.md` — update the state diagram and "Restart refusal" section.
- **modify** `tests/unit/resources/test_teardown.py` — add `is_timeout_only_refusal` coverage.
- **modify** `tests/unit/resources/test_lifecycle_transitions.py` — add coverage for the new `STOPPED -> EXHAUSTED_DEAD` transition.
- **modify** `tests/unit/resources/lifecycle/test_shutdown.py` — add `is_teardown_confirmed_quiescent` coverage.
- **create** `tests/integration/test_service_watcher_refusal_scoping.py` — confirmed-death degrade, unconfirmed-death escalation, `PERMANENT`-still-escalates, `WebsocketService`-still-escalates, and bystander-guard integration tests.

## Known Risks (accepted for this iteration)

- **No cross-service correlation.** The Problem section motivates this fix with system-wide resource pressure (a Raspberry Pi, momentary network latency) — a condition that doesn't respect service boundaries. If the host is under enough load to blow one service's teardown timeout, it's plausible for several `TRANSIENT`/`TEMPORARY` services to blow theirs within the same window. Each `execute_restart()`/`cooldown_and_retry()` runs as an independent spawned task with its own independent confirmation wait — there is no shared counter and no "N services degraded within window ⇒ escalate to root shutdown anyway" fallback. It's possible for multiple services to independently land at `EXHAUSTED_DEAD` while others keep running, rather than the single clean root shutdown + supervisor restart today's behavior would produce for the same correlated event. Accepted as an out-of-scope gap for this iteration — a cross-service circuit breaker is a legitimate follow-up but adds real design surface (threshold tuning, shared state across otherwise-independent per-service tasks) this design doesn't scope for.

## Dependencies and Assumptions

- Assumes [#1767](https://github.com/NodeJSmith/hassette/issues/1767) (generic per-service reconstruction) remains unbuilt for now. This is a real tradeoff, not a wash: today, `RestartRefusedError` is a `FatalError` that reaches `run_forever()` and exits the process non-zero (`cli/commands/run.py`'s `except FatalError: raise SystemExit(1)`), which any process supervisor (systemd `Restart=on-failure`, Docker restart policy) already auto-recovers from *automatically*, with no human involved. The new confirmed-quiescent branch never exits the process, so a service that reaches `EXHAUSTED_DEAD` this way stays down until a human notices and restarts the process manually — there is no automatic recovery for that one service until #1767 ships. What's gained in exchange: the failure is contained to that one service (and, per the exclusions above, never to `WebsocketService` or a `PERMANENT` service) instead of taking every other service and app down with it. Whether that tradeoff is worth it depends on the specific service — see the "Known downstream degradation" list above for what's actually lost per service.
- Bounds the confirmation wait to half of `resource_shutdown_timeout_seconds` rather than introducing a new config field or reusing the full value. The original teardown attempt already spent up to the full timeout discovering the resource wouldn't die cleanly — reusing the full timeout again would let a genuinely-stuck resource take up to 2x as long to reach root shutdown, a real regression to failure-detection speed on the resource-constrained hosts this design is motivated by. Half the existing timeout gives a real confirmation window without doubling worst-case time-to-escalation, and needs no new config surface.

## Addendum

### 2026-09-01: `RestartSpec.degrade_on_confirmed_quiescent_refusal` renamed to `allow_scoped_degradation`

The field this design introduced as `degrade_on_confirmed_quiescent_refusal` (referenced throughout the "Files to Modify" section above) was renamed to `allow_scoped_degradation` before merge. The original name leaked an implementation detail (`is_teardown_confirmed_quiescent()`, the internal polling mechanism used to verify quiescence) into a field a service author has to read and set; the new name states the actual decision — does a timeout-only refusal degrade just this service, or escalate to root shutdown — without requiring the reader to already know how that decision gets verified. Behavior is unchanged; this is a rename only.

### 2026-09-01: `_shutdown_hooks_completed` guards `_force_terminal()`'s `record_cause` on a body timeout

`_run_shutdown_coordinator()`'s shutdown-body-timeout branch unconditionally suppressed `FORCED_TERMINAL` evidence via `_force_terminal(record_cause=False)`, regardless of whether this resource's own shutdown hooks (`before_shutdown`/`on_shutdown`/`after_shutdown` — where most resources release bus subscriptions, scheduled jobs, and other held resources) had actually run before the timeout fired. Since `_force_terminal()` never calls hooks itself, and this design's scoped-degradation path can leave the process running afterward instead of always exiting, a resource whose hooks never got a chance to run — or whose hooks ran but one raised — could be classified `is_timeout_only_refusal` and silently degraded while leaking real resources for the rest of the process's life. Reported against PR #1782.

Added `_shutdown_hooks_completed: bool` (`src/hassette/resources/mixins.py`), set by `Resource._shutdown_body()`/`Service._shutdown_body()` right after their `run_hooks()` call(s) return, `True` only when every shutdown hook ran without raising. `_run_shutdown_coordinator()` now passes `record_cause=not resource._shutdown_hooks_completed` instead of always `False` — `FORCED_TERMINAL` stays suppressed once hooks have run cleanly (nothing new is at risk of leaking; whatever remains has its own evidence paths), but is recorded for real when hooks never completed or one raised, correctly escalating instead of silently degrading.

### 2026-09-02: `CommandExecutor`'s "Known downstream degradation" entry was wrong — now excluded from scoped degradation

The "Known downstream degradation" list above states `CommandExecutor` dead "doesn't execute automations itself. Losing it drops telemetry records; nothing stops running." That's false: `CommandExecutor.execute_handler()`/`execute_job()` spawn user-configured error handlers via `self.task_bucket.spawn()` when an invocation fails. Once `CommandExecutor` degrades to `EXHAUSTED_DEAD`, its `task_bucket` is sealed, and that `spawn()` call raises `RuntimeError` uncaught — escaping the invocation path and silently breaking every app's error handlers app-wide, not just telemetry. `CommandExecutor.restart_spec` now sets `allow_scoped_degradation=False`, the same opt-out already used for `WebsocketService`/`WebApiService`, so a restart refusal escalates to root shutdown instead. Reported against PR #1782.
