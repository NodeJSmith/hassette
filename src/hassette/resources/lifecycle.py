"""Module-level lifecycle state-transition functions for Hassette resources.

These functions replace methods that previously lived on ``LifecycleMixin``. They accept the
resource as their first argument instead of being bound methods, so lifecycle transitions are
invoked as ``handle_failed(resource, exc)`` instead of ``resource.handle_failed(exc)``.

Functions are typed against ``_LifecycleHostP`` (see ``hassette.resources.mixins``) at the public
signature to keep the contract minimal, then narrowed internally to ``LifecycleMixin`` — the
concrete implementation always in play at runtime — to access the mutable lifecycle state
(``ready_event``, ``shutdown_event``, ``_ready_reason``, ``_init_task``, ``status``) that the
Protocol intentionally does not declare.
"""

import asyncio
import typing
from contextlib import suppress
from typing import Any

from hassette.events import HassetteServiceEvent
from hassette.exceptions import LifecycleReentryError, RestartRefusedError
from hassette.resources.mixins import LifecycleMixin, _LifecycleHostP
from hassette.resources.teardown import (
    RestartSafety,
    TeardownCause,
    TeardownReport,
    add_teardown_evidence,
    merge_teardown_reports,
)
from hassette.types.enums import TERMINAL_STATUSES, ResourceStatus

if typing.TYPE_CHECKING:
    from collections.abc import Coroutine


def create_service_status_event(
    resource: _LifecycleHostP,
    status: ResourceStatus,
    exception: Exception | BaseException | None = None,
    ready: bool = False,
    ready_phase: str | None = None,
) -> HassetteServiceEvent:
    """Build a service-status event from the resource's current state.

    Args:
        resource: The resource emitting the event.
        status: The new lifecycle status.
        exception: Optional exception that triggered the transition.
        ready: Whether the resource is currently ready.
        ready_phase: Human-readable reason for the readiness state.
    """
    return HassetteServiceEvent.from_service_status(
        resource_name=resource.class_name,
        role=resource.role,
        status=status,
        previous_status=typing.cast("LifecycleMixin", resource)._previous_status,
        exception=exception,
        ready=ready,
        ready_phase=ready_phase,
    )


def mark_ready(resource: _LifecycleHostP, reason: str | None = None) -> None:
    """Mark the instance as ready.

    Args:
        resource: The resource to mark ready.
        reason: Optional reason for readiness.
    """
    resource = typing.cast("LifecycleMixin", resource)
    if resource.ready_event.is_set():
        resource.logger.debug("%s already ready, skipping reason %s", resource.unique_name, reason)
        return
    resource.logger.debug("ready: %s", reason or "no reason provided")
    resource._ready_reason = reason
    resource.ready_event.set()


def mark_not_ready(resource: _LifecycleHostP, reason: str | None = None) -> None:
    """Mark the instance as not ready.

    Args:
        resource: The resource to mark not ready.
        reason: Optional reason for lack of readiness.
    """
    resource = typing.cast("LifecycleMixin", resource)
    if not resource.ready_event.is_set():
        resource.logger.debug("%s already not ready, skipping reason %s", resource.unique_name, reason)
        return

    resource._ready_reason = reason
    resource.ready_event.clear()


def request_shutdown(resource: _LifecycleHostP, reason: str | None = None) -> None:
    """Set the sticky shutdown flag. Idempotent."""
    resource = typing.cast("LifecycleMixin", resource)
    if not resource.shutdown_event.is_set():
        resource.logger.info("%s shutdown requested: %s", resource.unique_name, reason or "no reason", stacklevel=2)
        resource.shutdown_event.set()
    # clear readiness early so callers back off
    mark_not_ready(resource, reason or "shutdown requested")


def start(resource: _LifecycleHostP) -> None:
    """Start the instance by spawning its coordinated ``initialize()`` front door in a task.

    Performs the same synchronous re-entry and restart-refusal checks the coordinator itself
    performs, then spawns a joiner task that calls the public ``initialize()`` front door.
    Deliberately does **not** assign ``_init_task`` here and does **not** reset shutdown
    state (``shutdown_event``, the stored teardown report) — only an accepted initialization
    attempt inside the coordinator does that. See ``coordinate_initialize()``.
    """
    resource = typing.cast("LifecycleMixin", resource)
    reject_lifecycle_reentry(resource, "start")

    if resource._init_task is not None and not resource._init_task.done():
        resource.logger.debug("%s already started or running", resource.unique_name, stacklevel=2)
        return

    report = resource._teardown_report
    if report is not None and report.restart_safety is RestartSafety.UNSAFE:
        raise RestartRefusedError(resource.unique_name, report)

    resource.logger.debug("%s starting", resource.unique_name)
    resource.task_bucket.spawn(resource.initialize(), name="resource:resource_initialize")


def cancel(resource: _LifecycleHostP) -> None:
    """Cancel the main task of the instance, if it is running."""
    resource = typing.cast("LifecycleMixin", resource)
    if resource._init_task and not resource._init_task.done():
        resource._init_task.cancel()
        resource.logger.debug("%s cancelled task", resource.unique_name)
        return

    resource.logger.debug("%s no running task to cancel", resource.unique_name)


# dup-ignore-start: lifecycle state handlers share cast → guard → transition → emit-event structure by design
async def handle_stop(resource: _LifecycleHostP) -> None:
    """Transition the resource to STOPPED and emit a status event.

    Args:
        resource: The resource to stop.
    """
    resource = typing.cast("LifecycleMixin", resource)
    if resource.status == ResourceStatus.STOPPED:
        resource.logger.debug("%s already stopped", resource.unique_name, stacklevel=2)
        return

    resource.logger.debug("%s stopping", resource.unique_name, stacklevel=2)
    resource.status = ResourceStatus.STOPPED
    mark_not_ready(resource, "Stopped")
    event = create_service_status_event(
        resource, ResourceStatus.STOPPED, ready=resource.is_ready(), ready_phase=resource._ready_reason
    )
    await resource.hassette.send_event(event)


async def handle_failed(resource: _LifecycleHostP, exception: BaseException) -> None:
    """Transition the resource to FAILED and emit a status event.

    Args:
        resource: The resource that failed.
        exception: The exception that caused the failure.
    """
    resource = typing.cast("LifecycleMixin", resource)
    if resource.status == ResourceStatus.FAILED:
        resource.logger.debug("%s already in failed state", resource.unique_name, stacklevel=2)
        return

    if resource.status in TERMINAL_STATUSES:
        # The resource already reached a terminal end-state: STOPPED (clean finish) or
        # EXHAUSTED_DEAD (permanent restart-budget failure). A late error does not retroactively
        # un-stop it, so failing it is benign — and VALID_TRANSITIONS forbids both → FAILED.
        # This happens during teardown when a submit-after-shutdown error ("cannot schedule new
        # futures after shutdown") surfaces on an already-stopped resource; driving it to FAILED
        # would raise InvalidLifecycleTransitionError under strict_lifecycle — the error that
        # escaped harness teardown and leaked the global Hassette singleton on Python 3.11.
        # Only terminal end-states are guarded. Non-terminal states (NOT_STARTED, STARTING,
        # RUNNING, STOPPING, EXHAUSTED_COOLING) keep failing normally — a failure there is real,
        # and callers do invoke handle_failed() on a not-yet-started resource.
        resource.logger.debug(
            "%s already terminal (%s); ignoring failure: %s - %s",
            resource.unique_name,
            resource.status,
            type(exception).__name__,
            exception,
            stacklevel=2,
        )
        return

    resource.logger.exception("%s failed: %s - %s", resource.unique_name, type(exception).__name__, str(exception))
    resource.status = ResourceStatus.FAILED
    mark_not_ready(resource, "Failed")
    event = create_service_status_event(
        resource, ResourceStatus.FAILED, exception, ready=resource.is_ready(), ready_phase=resource._ready_reason
    )
    await resource.hassette.send_event(event)


async def handle_running(resource: _LifecycleHostP) -> None:
    """Transition the resource to RUNNING and emit a status event.

    Args:
        resource: The resource that is now running.
    """
    resource = typing.cast("LifecycleMixin", resource)
    if resource.status == ResourceStatus.RUNNING:
        resource.logger.debug("%s already running", resource.unique_name, stacklevel=2)
        return

    resource.logger.debug("%s running", resource.unique_name, stacklevel=2)
    resource.status = ResourceStatus.RUNNING
    event = create_service_status_event(
        resource, ResourceStatus.RUNNING, ready=resource.is_ready(), ready_phase=resource._ready_reason
    )
    await resource.hassette.send_event(event)


async def handle_starting(resource: _LifecycleHostP) -> None:
    """Transition the resource to STARTING and emit a status event.

    Args:
        resource: The resource that is starting.
    """
    resource = typing.cast("LifecycleMixin", resource)
    if resource.status == ResourceStatus.STARTING:
        resource.logger.debug("%s already starting", resource.unique_name, stacklevel=2)
        return
    resource.logger.debug("%s starting", resource.unique_name, stacklevel=2)
    resource.status = ResourceStatus.STARTING
    event = create_service_status_event(
        resource, ResourceStatus.STARTING, ready=resource.is_ready(), ready_phase=resource._ready_reason
    )
    await resource.hassette.send_event(event)


async def handle_crash(resource: _LifecycleHostP, exception: Exception) -> None:
    """Transition the resource to CRASHED and emit a status event.

    Args:
        resource: The resource that crashed.
        exception: The exception that caused the crash.
    """
    resource = typing.cast("LifecycleMixin", resource)
    if resource.status == ResourceStatus.CRASHED:
        resource.logger.debug("%s already in crashed state", resource.unique_name, stacklevel=2)
        return

    resource.logger.error("%s crashed: %s - %s", resource.unique_name, type(exception).__name__, str(exception))
    resource.status = ResourceStatus.CRASHED
    mark_not_ready(resource, "Crashed")
    event = create_service_status_event(
        resource, ResourceStatus.CRASHED, exception, ready=resource.is_ready(), ready_phase=resource._ready_reason
    )
    await resource.hassette.send_event(event)


# dup-ignore-end


def reject_lifecycle_reentry(resource: _LifecycleHostP, method_name: str) -> None:
    """Raise ``LifecycleReentryError`` when a lifecycle front door is called from its own
    active initialization coordinator, shutdown coordinator, or shutdown body.

    Every public front door (``initialize()``, ``start()``, ``restart()``, ``shutdown()``)
    calls this first, before creating, joining, or cancelling any lifecycle task. A hook that
    calls back into its own owner's lifecycle orchestration cannot be joined or cancelled
    safely -- the calling task *is* the coordinator or body being awaited.

    Args:
        resource: The resource whose lifecycle task identity is being checked.
        method_name: The name of the front-door method performing the check, used in the
            raised error's message.
    """
    resource = typing.cast("LifecycleMixin", resource)
    current = asyncio.current_task()
    if current is not None and current in (resource._init_task, resource._shutdown_task, resource._shutdown_body_task):
        raise LifecycleReentryError(resource.unique_name, method_name)


def _create_lifecycle_task(coro: "Coroutine[Any, Any, Any]", *, name: str) -> asyncio.Task:
    """Create a lifecycle-owned task outside TaskBucket ownership.

    Uses the ``asyncio.Task`` constructor directly (not ``loop.create_task()``), the same
    mechanism Hassette's own task factory (``make_task_factory``) uses internally. This
    bypasses the loop's custom task factory, which would otherwise attribute the task to
    whichever TaskBucket is current in context. The shutdown body cancels TaskBucket work, so
    putting the coordinator or body task in that same bucket would create circular
    self-cancellation.
    """
    loop = asyncio.get_running_loop()
    return asyncio.Task(coro, loop=loop, name=name)


def _install_exception_observer(resource: _LifecycleHostP, task: asyncio.Task, label: str) -> None:
    """Attach a done callback that retrieves and logs any exception the task raised.

    Ensures every lifecycle coordinator/body task is exception-observed even when every
    external joiner cancels its own wait -- an unretrieved task exception would otherwise
    surface as an "exception was never retrieved" warning with no other observer.
    """
    resource = typing.cast("LifecycleMixin", resource)

    def _observe(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            resource.logger.exception(
                "%s: %s task %r finished with an unhandled exception",
                resource.unique_name,
                label,
                t.get_name(),
                exc_info=exc,
            )

    task.add_done_callback(_observe)


async def coordinate_initialize(resource: _LifecycleHostP) -> None:
    """Coordinator front door for ``initialize()``.

    Every initialization path -- direct ``initialize()`` calls, ``start()``'s spawned joiner,
    and ``restart()`` -- funnels through this function, so ``_init_task`` is authoritative for
    every attempt. See the "Minimal lifecycle coordinator" section of
    ``design/specs/105-teardown-restart-safety/design.md`` for the full admission sequence.
    """
    resource = typing.cast("LifecycleMixin", resource)
    reject_lifecycle_reentry(resource, "initialize")

    shutdown_task = resource._shutdown_task
    if shutdown_task is not None and not shutdown_task.done():
        # Initialization requested during shutdown waits for that shutdown outcome before
        # deciding whether a new incarnation may start.
        await asyncio.shield(shutdown_task)

    report = resource._teardown_report
    if report is not None and report.restart_safety is RestartSafety.UNSAFE:
        raise RestartRefusedError(resource.unique_name, report)

    init_task = resource._init_task
    if init_task is None or init_task.done():
        if resource._teardown_report is not None:
            # First accepted initialization after a clean (SAFE) teardown: consume the report
            # and reopen the resources that a completed shutdown attempt sealed/cleared.
            resource._teardown_report = None
            resource._shutdown_task = None
            resource.task_bucket.reopen()
            resource.shutdown_event.clear()
        init_task = _create_lifecycle_task(
            resource._initialize_body(), name=f"resource:initialize:{resource.unique_name}"
        )
        _install_exception_observer(resource, init_task, "initialization coordinator")
        resource._init_task = init_task

    await asyncio.shield(init_task)


async def _observe_active_initializer(resource: "LifecycleMixin") -> bool:
    """Cancel and bound-observe an active ``_init_task`` before shutdown hooks run.

    Returns ``True`` when the initializer was still pending after the bounded wait (adds
    ``TeardownCause.INITIALIZATION_TASK_PENDING`` to the shutdown report), ``False`` otherwise
    (including when there was no active initializer to observe).
    """
    init_task = resource._init_task
    if init_task is None or init_task.done():
        return False

    init_task.cancel()
    timeout = resource.hassette.config.lifecycle.resource_shutdown_timeout_seconds
    _done, pending = await asyncio.wait([init_task], timeout=timeout)
    if pending:
        return True

    with suppress(BaseException):
        init_task.exception()
    return False


async def _run_shutdown_coordinator(resource: "LifecycleMixin") -> TeardownReport:
    """Body of the shutdown coordinator task (``_shutdown_task``).

    Cancels and observes an active initializer, transitions status and requests shutdown,
    then bounds observation of the class-specific ``_shutdown_body()`` for
    ``resource_shutdown_timeout_seconds``. Stores and returns the merged report.

    If something external cancels this coordinator task directly (``_force_terminal()`` may do
    this for an unresponsive child from an ancestor's own shutdown body -- see
    ``Resource._force_terminal()``), the cancellation is converted to a normal
    ``RestartSafety.UNSAFE`` return *only* when force-terminal evidence was already stored
    before the cancellation was requested. Every joined caller then receives that report rather
    than ``CancelledError``. A cancellation with no pre-recorded evidence is a genuine error and
    propagates normally.
    """
    try:
        initialization_pending = await _observe_active_initializer(resource)

        if resource._status not in TERMINAL_STATUSES:
            resource.status = ResourceStatus.STOPPING
        request_shutdown(resource, f"{resource.unique_name} shutdown")

        body_task = _create_lifecycle_task(
            resource._shutdown_body(), name=f"resource:shutdown_body:{resource.unique_name}"
        )
        _install_exception_observer(resource, body_task, "shutdown body")
        resource._shutdown_body_task = body_task

        if typing.cast("object", resource) is resource.hassette:
            # The root resource's own _shutdown_body() (Hassette._shutdown_body()) already
            # self-bounds with total_shutdown_timeout_seconds via its own asyncio.timeout(). The
            # coordinator's outer wait must track that same budget instead of imposing the
            # generic per-resource timeout on top of it — otherwise a body that's still working
            # past resource_shutdown_timeout_seconds but within total_shutdown_timeout_seconds
            # gets abandoned and force-terminated here before its own budget ever gets a chance
            # to fire. Using the root's total budget directly (not max() against the per-resource
            # timeout) preserves the reverse relationship too: a total timeout intentionally set
            # smaller than the per-resource one (e.g. in tests) still bounds the wait correctly.
            timeout = resource.hassette.config.lifecycle.total_shutdown_timeout_seconds
        else:
            timeout = resource.hassette.config.lifecycle.resource_shutdown_timeout_seconds
        done, _pending = await asyncio.wait([body_task], timeout=timeout)

        if body_task in done:
            try:
                report = body_task.result()
            except asyncio.CancelledError:  # noqa: ASYNC103 — body cancellation is bounded evidence for this
                # coordinator, not a fatal event for it: convert to SHUTDOWN_BODY_FAILED instead of propagating.
                report = TeardownReport(
                    causes=(TeardownCause.SHUTDOWN_BODY_FAILED,), failed_operations=("_shutdown_body",)
                )
            except Exception:
                resource.logger.exception("Shutdown body for %s raised", resource.unique_name)
                report = TeardownReport(
                    causes=(TeardownCause.SHUTDOWN_BODY_FAILED,), failed_operations=("_shutdown_body",)
                )
        else:
            resource.logger.warning("%s shutdown body did not complete within %ss", resource.unique_name, timeout)
            report = TeardownReport(causes=(TeardownCause.SHUTDOWN_BODY_TIMED_OUT,))
            resource._force_terminal()
            if not body_task.done():
                body_task.cancel()
                report = add_teardown_evidence(
                    report,
                    causes=(TeardownCause.SHUTDOWN_BODY_PENDING,),
                    pending_tasks=(body_task.get_name(),),
                )

        if initialization_pending:
            report = add_teardown_evidence(report, causes=(TeardownCause.INITIALIZATION_TASK_PENDING,))
    except asyncio.CancelledError:  # noqa: ASYNC103 — re-raised below when no force evidence was stored first
        existing = resource._teardown_report
        if existing is None:
            raise
        body_task = resource._shutdown_body_task
        if body_task is not None and not body_task.done():
            body_task.cancel()
        return existing  # noqa: ASYNC104 — FORCED_TERMINAL (or other) evidence was already stored before this
        # coordinator was cancelled, so every joined caller gets that report instead of CancelledError.

    # A retained body task (or a concurrent _force_terminal() call) may already have stored
    # evidence on this attempt (e.g. FORCED_TERMINAL) before this point is reached. Merge
    # rather than overwrite so a later completion can only add evidence, never remove it.
    existing = resource._teardown_report
    if existing is not None:
        report = merge_teardown_reports(existing, report)

    resource._teardown_report = report
    return report


async def coordinate_shutdown(resource: _LifecycleHostP) -> TeardownReport:
    """Coordinator front door for ``shutdown()``.

    Creates ``_shutdown_task`` exactly once per shutdown attempt; every caller (concurrent or
    repeated) shields and awaits that same task, so a repeated call after completion returns
    the stored report without rerunning hooks. Task selection and assignment happen without an
    intervening ``await`` so the check-and-create step is atomic on the event loop.
    """
    resource = typing.cast("LifecycleMixin", resource)
    reject_lifecycle_reentry(resource, "shutdown")

    task = resource._shutdown_task
    if task is None:
        task = _create_lifecycle_task(
            _run_shutdown_coordinator(resource), name=f"resource:shutdown:{resource.unique_name}"
        )
        _install_exception_observer(resource, task, "shutdown coordinator")
        resource._shutdown_task = task

    return await asyncio.shield(task)
