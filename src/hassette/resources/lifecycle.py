"""Module-level lifecycle state-transition functions for Hassette resources.

These functions replace methods that previously lived on ``LifecycleMixin``. They accept the
resource as their first argument instead of being bound methods, so lifecycle transitions are
invoked as ``handle_failed(resource, exc)`` instead of ``resource.handle_failed(exc)``.

Functions are typed against ``_LifecycleHostP`` (see ``hassette.resources.mixins``) at the public
signature to keep the contract minimal, then narrowed internally to ``LifecycleMixin`` — the
concrete implementation always in play at runtime — to access the mutable lifecycle state
(``ready_event``, ``shutdown_event``, ``_ready_reason``, ``_init_task``, ``_pending_start_task``,
``status``) that the Protocol intentionally does not declare.
"""

import asyncio
import logging
import threading
import typing
from contextlib import suppress
from typing import Any

from hassette_wire import ResourceStatus

from hassette.events import HassetteServiceEvent
from hassette.exceptions import LifecycleReentryError, RestartRefusedError
from hassette.resources.mixins import LifecycleMixin, _LifecycleHostP
from hassette.resources.shutdown_deadline import elapsed_since, format_bound, shutdown_hook_bound
from hassette.resources.teardown import (
    TeardownCause,
    TeardownReport,
    add_teardown_evidence,
    merge_teardown_reports,
)
from hassette.types.enums import TERMINAL_STATUSES, ResourceRole

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
        resource.lifecycle_logger.debug("%s already ready, skipping reason %s", resource.unique_name, reason)
        return
    resource.lifecycle_logger.debug("ready: %s", reason or "no reason provided")
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
        resource.lifecycle_logger.debug("%s already not ready, skipping reason %s", resource.unique_name, reason)
        return

    resource._ready_reason = reason
    resource.ready_event.clear()


def set_ready_reason(resource: _LifecycleHostP, reason: str | None) -> None:
    """Replace the readiness reason without changing readiness.

    For a resource whose readiness stays fixed while the status it reports changes, such as
    ``WebsocketService`` showing the Home Assistant connection's state.

    Args:
        resource: The resource whose reason to replace.
        reason: The new reason.
    """
    resource = typing.cast("LifecycleMixin", resource)
    resource._ready_reason = reason


def request_shutdown(resource: _LifecycleHostP, reason: str | None = None) -> None:
    """Set the sticky shutdown flag. Idempotent."""
    resource = typing.cast("LifecycleMixin", resource)
    if not resource.shutdown_event.is_set():
        resource.lifecycle_logger.debug(
            "%s shutdown requested: %s", resource.unique_name, reason or "no reason", stacklevel=2
        )
        resource.shutdown_event.set()
    # clear readiness early so callers back off
    mark_not_ready(resource, reason or "shutdown requested")


def start(resource: _LifecycleHostP) -> asyncio.Task[None] | None:
    """Start the instance by spawning its coordinated ``initialize()`` front door in a task.

    Performs the same synchronous re-entry and restart-refusal checks the coordinator itself
    performs, then spawns a joiner task that calls the public ``initialize()`` front door.
    Deliberately does **not** assign ``_init_task`` here and does **not** reset shutdown
    state (``shutdown_event``, the stored teardown report) — only an accepted initialization
    attempt inside the coordinator does that. See ``coordinate_initialize()``.

    The joiner is created outside the resource's own TaskBucket (the same lifecycle-owned task
    mechanism the coordinator and shutdown body use, not ``task_bucket.spawn()``): a clean
    teardown seals the bucket, and reopening it is itself one of the effects of the accepted
    initialization attempt this joiner triggers, so admitting the joiner *through* the bucket
    it is about to reopen would reject it with a sealed-bucket error.

    Thread-safe: when called from a thread other than the event loop's own (e.g. a sync handler
    running on the dedicated sync-handler thread pool), re-dispatches itself onto the loop
    thread via ``call_soon_threadsafe`` and returns immediately -- restoring the cross-thread
    reach ``TaskBucket.spawn()`` used to provide before this function's joiner creation moved to
    ``create_lifecycle_task()`` (see its docstring), which requires an already-running loop on
    the calling thread. Unlike ``spawn()``'s cross-thread path, this is pure fire-and-forget: the
    calling thread has already returned by the time the re-dispatched call actually runs, so a
    ``LifecycleReentryError`` or ``RestartRefusedError`` raised at that point cannot propagate
    back to it and is logged here instead.

    ``loop_thread_id`` is ``None`` before ``run_forever()`` captures it -- only redispatches when
    positively known to be on a different thread, rather than treating "unknown" as "different."
    Comparing against ``None`` directly would redispatch on every call made before the loop
    starts (including from the correct future loop thread) and then crash on
    ``resource.hassette.loop`` (``RuntimeError: Event loop is not running``, since ``_loop`` and
    ``_loop_thread_id`` are set together).

    Returns:
        The task the current initialization attempt runs on, so a caller can join the attempt
        without starting a new one: the joiner this call spawned, the one a previous call left
        pending, or the in-flight ``_init_task``. Each raises the attempt's exception when it
        fails. ``None`` only on cross-thread redispatch, where no task exists yet.
    """
    resource = typing.cast("LifecycleMixin", resource)

    loop_thread_id = resource.hassette.loop_thread_id
    if loop_thread_id is not None and threading.get_ident() != loop_thread_id:

        def _start_on_loop_thread() -> None:
            try:
                start(resource)
            except Exception:
                resource.lifecycle_logger.exception(
                    "%s: cross-thread start() failed after re-dispatch onto the loop thread",
                    resource.unique_name,
                )

        resource.hassette.loop.call_soon_threadsafe(_start_on_loop_thread)
        return None

    reject_lifecycle_reentry(resource, "start")

    if resource._init_task is not None and not resource._init_task.done():
        resource.lifecycle_logger.debug("%s already started or running", resource.unique_name, stacklevel=2)
        return resource._init_task

    # A second guard, not a duplicate of the one above: _init_task is only assigned once the
    # joiner below actually runs coordinate_initialize(), which can be a turn or more later.
    # Without this check, a second start() call issued before that first turn would see
    # _init_task still None and spawn a second, redundant joiner. See _pending_start_task's
    # docstring for the shutdown-race this same field also closes.
    if resource._pending_start_task is not None and not resource._pending_start_task.done():
        resource.lifecycle_logger.debug("%s start already pending", resource.unique_name, stacklevel=2)
        return resource._pending_start_task

    report = resource._teardown_report
    if report is not None and not report.is_restart_safe:
        raise RestartRefusedError(resource.unique_name, report)

    resource.lifecycle_logger.debug("%s starting", resource.unique_name)
    joiner = create_lifecycle_task(resource.initialize(), name="resource:resource_initialize")
    # The joiner usually re-raises the coordinator's own exception (via asyncio.shield), so its
    # observer logs that at DEBUG once _last_error_logged holds it. For an app-role resource the
    # inner layers log at DEBUG and record nothing, so with no initialize_instances() around this
    # start() the joiner's ERROR is the only one. Exceptions raised before the coordinator task
    # exists (a RestartRefusedError from coordinate_initialize()) also surface only here.
    _install_exception_observer(resource, joiner, "start joiner")
    resource._pending_start_task = joiner

    def _clear_pending_start(task: asyncio.Task) -> None:
        if resource._pending_start_task is task:
            resource._pending_start_task = None

    joiner.add_done_callback(_clear_pending_start)
    return joiner


def cancel(resource: _LifecycleHostP) -> None:
    """Cancel the main task of the instance, if it is running.

    Also cancels a still-pending ``start()`` joiner (``_pending_start_task``) when present --
    ``start()`` assigns that field synchronously but only assigns ``_init_task`` a turn or more
    later, once the joiner actually runs ``coordinate_initialize()``. Without this check, a
    ``cancel()`` called in the same event-loop turn as ``start()`` would see ``_init_task`` still
    ``None``, report nothing to cancel, and let the queued joiner go on to initialize the
    resource despite the cancellation request. Cancel-and-forget is safe here: ``cancel()`` is
    synchronous and cannot await the joiner the way ``_observe_active_initializer()`` does, but
    the joiner's own ``add_done_callback(_clear_pending_start)`` (set up in ``start()``) clears
    ``_pending_start_task`` once it settles, and ``_install_exception_observer()`` already
    ensures its exception/cancellation is observed.

    Thread-safe: mirrors ``start()``'s cross-thread redispatch (see its docstring) via
    ``call_soon_threadsafe`` when called off the loop thread. This is what preserves ordering
    for a sync handler that calls ``start(resource)`` immediately followed by
    ``cancel(resource)``: both redispatches land on the loop's ``call_soon`` queue in the same
    FIFO order they were submitted, so this cancel's redispatched callback always runs after
    that start's, and finds whatever start() actually set (``_pending_start_task`` or
    ``_init_task``) instead of racing ahead of the not-yet-processed start() callback and
    finding nothing to cancel.
    """
    resource = typing.cast("LifecycleMixin", resource)

    loop_thread_id = resource.hassette.loop_thread_id
    if loop_thread_id is not None and threading.get_ident() != loop_thread_id:

        def _cancel_on_loop_thread() -> None:
            try:
                cancel(resource)
            except Exception:
                resource.lifecycle_logger.exception(
                    "%s: cross-thread cancel() failed after re-dispatch onto the loop thread",
                    resource.unique_name,
                )

        resource.hassette.loop.call_soon_threadsafe(_cancel_on_loop_thread)
        return

    cancelled_something = False

    if resource._pending_start_task is not None and not resource._pending_start_task.done():
        resource._pending_start_task.cancel()
        resource.lifecycle_logger.debug("%s cancelled pending start joiner", resource.unique_name)
        cancelled_something = True

    if resource._init_task and not resource._init_task.done():
        resource._init_task.cancel()
        resource.lifecycle_logger.debug("%s cancelled task", resource.unique_name)
        cancelled_something = True

    if not cancelled_something:
        resource.lifecycle_logger.debug("%s no running task to cancel", resource.unique_name)


# dup-ignore-start: lifecycle state handlers share cast → guard → transition → emit-event structure by design
async def handle_stop(resource: _LifecycleHostP) -> None:
    """Transition the resource to STOPPED and emit a status event.

    Args:
        resource: The resource to stop.
    """
    resource = typing.cast("LifecycleMixin", resource)
    if resource.status == ResourceStatus.STOPPED:
        resource.lifecycle_logger.debug("%s already stopped", resource.unique_name, stacklevel=2)
        return

    resource.lifecycle_logger.debug("%s stopping", resource.unique_name, stacklevel=2)
    resource.status = ResourceStatus.STOPPED
    mark_not_ready(resource, "Stopped")
    event = create_service_status_event(
        resource, ResourceStatus.STOPPED, ready=resource.is_ready(), ready_phase=resource._ready_reason
    )
    await resource.hassette.send_event(event)


async def handle_failed(resource: _LifecycleHostP, exception: BaseException, *, log_level: int = logging.ERROR) -> None:
    """Transition the resource to FAILED and emit a status event.

    Args:
        resource: The resource that failed.
        exception: The exception that caused the failure.
        log_level: Level for the "<resource> failed" traceback log below. Defaults to ERROR.
            Callers pass ``logging.DEBUG`` when a strictly outer, decision-owning layer already
            logs this same exception at ERROR -- see ``run_hooks()`` in
            ``hassette.resources.operations``, which demotes this for app-role resources during
            initialization (``AppLifecycleService.initialize_instances()`` is that outer layer)
            but leaves it at ERROR for every other resource, since those have no other logger
            for an initialization failure. Only an ERROR-or-higher log is recorded in
            ``_last_error_logged``, so a demoted failure is still logged at ERROR by a later
            exception observer when no outer layer exists.
    """
    resource = typing.cast("LifecycleMixin", resource)
    if resource.status == ResourceStatus.FAILED:
        resource.lifecycle_logger.debug("%s already in failed state", resource.unique_name, stacklevel=2)
        return

    if resource.status in TERMINAL_STATUSES:
        # The resource already reached its terminal end-state, STOPPED. A late error on an
        # already-terminal resource must not move it to FAILED: it does not retroactively un-stop it.
        # This happens during teardown when a submit-after-shutdown error ("cannot schedule new
        # futures after shutdown") surfaces on an already-stopped resource.
        # Every other state (NOT_STARTED, STARTING, RUNNING, STOPPING) keeps failing normally — a
        # failure there is real, and callers do invoke handle_failed() on a not-yet-started resource.
        resource.lifecycle_logger.debug(
            "%s already terminal (%s); ignoring failure: %s - %s",
            resource.unique_name,
            resource.status,
            type(exception).__name__,
            exception,
            stacklevel=2,
        )
        return

    resource.lifecycle_logger.log(
        log_level,
        "%s failed: %s - %s",
        resource.unique_name,
        type(exception).__name__,
        str(exception),
        exc_info=exception,
    )
    if log_level >= logging.ERROR:
        resource._last_error_logged = exception
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
        resource.lifecycle_logger.debug("%s already running", resource.unique_name, stacklevel=2)
        return

    resource.lifecycle_logger.debug("%s running", resource.unique_name, stacklevel=2)
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
        resource.lifecycle_logger.debug("%s already starting", resource.unique_name, stacklevel=2)
        return
    resource.lifecycle_logger.debug("%s starting", resource.unique_name, stacklevel=2)
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
        resource.lifecycle_logger.debug("%s already in crashed state", resource.unique_name, stacklevel=2)
        return

    resource.lifecycle_logger.error(
        "%s crashed: %s - %s", resource.unique_name, type(exception).__name__, str(exception), exc_info=exception
    )
    resource.status = ResourceStatus.CRASHED
    mark_not_ready(resource, "Crashed")
    event = create_service_status_event(
        resource, ResourceStatus.CRASHED, exception, ready=resource.is_ready(), ready_phase=resource._ready_reason
    )
    await resource.hassette.send_event(event)


# dup-ignore-end


def reject_lifecycle_reentry(resource: _LifecycleHostP, method_name: str) -> None:
    """Raise ``LifecycleReentryError`` when a lifecycle front door re-enters its own active lifecycle task.

    The active task is the resource's own initialization coordinator, shutdown coordinator, or shutdown body.

    Every public front door (``initialize()``, ``start()``, ``shutdown()``)
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


def create_lifecycle_task(coro: "Coroutine[Any, Any, Any]", *, name: str) -> asyncio.Task:
    """Create a lifecycle-owned task outside TaskBucket ownership.

    Not module-private despite the plain name -- ``shutdown_batch()`` (operations.py) and
    ``gather_all()`` (core/app_lifecycle_instances.py) also use this to create each task they
    gather at exit, for the same reason the coordinator/body tasks below need it: those
    calls happen after ``_run_task_bucket_shutdown_stage()`` has already sealed the resource's
    own TaskBucket, and for the root resource that bucket is also the loop's global fallback
    bucket (see ``make_task_factory``). Letting ``asyncio.gather()`` create those child-shutdown
    tasks the normal way would route them through the now-sealed factory and reject every one
    immediately, silently aborting child teardown.

    Uses the ``asyncio.Task`` constructor directly (not ``loop.create_task()``), the same
    mechanism Hassette's own task factory (``make_task_factory``) uses internally. This
    bypasses the loop's custom task factory, which would otherwise attribute the task to
    whichever TaskBucket is current in context. The shutdown body cancels TaskBucket work, so
    putting the coordinator or body task in that same bucket would create circular
    self-cancellation.
    """
    loop = asyncio.get_running_loop()
    return asyncio.Task(coro, loop=loop, name=name)


def _install_exception_observer(
    resource: _LifecycleHostP,
    task: asyncio.Task,
    label: str,
    *,
    log_level: int = logging.ERROR,
) -> None:
    """Attach a done callback that retrieves and logs any exception the task raised.

    Ensures every lifecycle coordinator/body task is exception-observed even when every
    external joiner cancels its own wait -- an unretrieved task exception would otherwise
    surface as an "exception was never retrieved" warning with no other observer.

    The first lifecycle log of an exception at ERROR records it in ``_last_error_logged``
    (``handle_failed()`` or one of these observers). An observer whose task raised that same
    exception object logs it at DEBUG instead, so each failure carries one ERROR traceback however
    many tasks re-raise it.

    Args:
        resource: The resource that owns the observed task.
        task: The lifecycle task to observe.
        label: Human-readable name for the task, used in the log message.
        log_level: Level for the "unhandled exception" log below. Defaults to ERROR.
            ``coordinate_initialize()`` passes ``logging.DEBUG`` for app-role resources -- their
            initialization exception is logged at ERROR by an outer layer:
            ``AppLifecycleService.initialize_instances()``, or ``start()``'s joiner observer when
            the app is started directly. Every other resource keeps ERROR here.
    """
    resource = typing.cast("LifecycleMixin", resource)

    def _observe(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            level = logging.DEBUG if exc is resource._last_error_logged else log_level
            if level >= logging.ERROR:
                resource._last_error_logged = exc
            resource.lifecycle_logger.log(
                level,
                "%s: %s task %r finished with an unhandled exception",
                resource.unique_name,
                label,
                t.get_name(),
                exc_info=exc,
            )

    task.add_done_callback(_observe)


async def coordinate_initialize(resource: _LifecycleHostP) -> None:
    """Coordinator front door for ``initialize()``.

    Every initialization path -- direct ``initialize()`` calls and ``start()``'s spawned
    joiner -- funnels through this function, so ``_init_task`` is authoritative for every
    attempt. See the "Minimal lifecycle coordinator" section of
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
    if report is not None and not report.is_restart_safe:
        raise RestartRefusedError(resource.unique_name, report)

    init_task = resource._init_task
    if init_task is None or init_task.done():
        if resource._teardown_report is not None:
            # First accepted initialization after a clean (SAFE) teardown: consume the report
            # and reopen the resources that a completed shutdown attempt sealed/cleared.
            resource._teardown_report = None
            resource._shutdown_task = None
            resource._shutdown_deadline = None
            resource.task_bucket.reopen()
            resource.shutdown_event.clear()
        init_task = create_lifecycle_task(
            resource._initialize_body(), name=f"resource:initialize:{resource.unique_name}"
        )
        # A new attempt raises new exception objects, so the previous attempt's record can go.
        resource._last_error_logged = None
        # App-role resources have an outer layer that logs this same exception at ERROR --
        # AppLifecycleService.initialize_instances()'s `await inst.initialize()`, or start()'s
        # joiner observer when the app is started directly. Demoting here avoids a second stacked
        # ERROR traceback for the exact same failure (see #1826). Every other resource (services,
        # framework internals) has no such outer logger, so it keeps ERROR.
        init_log_level = logging.DEBUG if resource.role == ResourceRole.APP else logging.ERROR
        _install_exception_observer(resource, init_task, "initialization coordinator", log_level=init_log_level)
        resource._init_task = init_task

    await asyncio.shield(init_task)


async def _cancel_pending_start(resource: "LifecycleMixin") -> None:
    """Cancel and await a still-queued ``start()`` joiner (``_pending_start_task``), if any.

    Safe to call whether or not the joiner has had an event-loop turn yet: cancelling before its
    first turn prevents the coroutine body (including ``coordinate_initialize()``'s synchronous
    admission mutations) from ever running at all, and cancelling it mid-flight is observed here
    via the bare ``await`` under ``suppress(asyncio.CancelledError)``. See
    ``_pending_start_task``'s docstring for the shutdown race this closes.

    Narrowly suppresses only ``asyncio.CancelledError`` from the joiner -- a bare
    ``suppress(BaseException)`` here would also swallow a ``CancelledError`` delivered to the
    *caller* of this function (the shutdown coordinator itself) while it awaits ``pending_start``,
    silently discarding a genuine cancellation request against the coordinator. It would also
    swallow ``KeyboardInterrupt``/``SystemExit`` raised from the joiner.
    """
    pending_start = resource._pending_start_task
    if pending_start is not None and not pending_start.done():
        pending_start.cancel()
        with suppress(asyncio.CancelledError):
            await pending_start
    resource._pending_start_task = None


async def _observe_active_initializer(resource: "LifecycleMixin") -> bool:
    """Cancel and bound-observe an active ``_init_task`` before shutdown hooks run.

    Also cancels a still-pending ``start()`` joiner (``_pending_start_task``) first, via
    ``_cancel_pending_start()``, before it has had a chance to run ``coordinate_initialize()``
    and create ``_init_task`` at all. Cancelling the joiner here is safe even once ``_init_task``
    already exists: the joiner is only ever awaited internally (via ``coordinate_initialize()``'s
    own ``asyncio.shield(init_task)``), so interrupting its outer await never affects ``_init_task``
    itself, which the check below continues to own.

    Returns ``True`` when the initializer was still pending after the bounded wait (adds
    ``TeardownCause.INITIALIZATION_TASK_PENDING`` to the shutdown report), ``False`` otherwise
    (including when there was no active initializer to observe).
    """
    await _cancel_pending_start(resource)

    init_task = resource._init_task
    if init_task is None or init_task.done():
        return False

    init_task.cancel()
    timeout = shutdown_hook_bound(resource)
    observe_start = asyncio.get_running_loop().time()
    _done, pending = await asyncio.wait([init_task], timeout=timeout)
    resource.lifecycle_logger.debug(
        "%s: initializer observation completed in %.2fs (%s bound)",
        resource.unique_name,
        elapsed_since(observe_start),
        format_bound(timeout),
    )
    if pending:
        return True

    # init_task.exception() raises CancelledError if the task was cancelled (the expected
    # outcome here, since it was cancelled a few lines up) -- retrieving it just marks the
    # exception as observed so it doesn't surface as an "exception was never retrieved" warning.
    with suppress(asyncio.CancelledError):
        init_task.exception()
    return False


async def _run_shutdown_coordinator(resource: "LifecycleMixin") -> TeardownReport:
    """Body of the shutdown coordinator task (``_shutdown_task``).

    Cancels and observes an active initializer, transitions status and requests shutdown, then waits
    for the class-specific ``_shutdown_body()`` without a bound of its own: the leaves inside the body
    bound themselves against the attempt's deadline, and only the operation's owner walks away from a
    body that outlives it (by force-terminating the resource). Stores and returns the merged report.

    If something external cancels this coordinator task directly (``_force_terminal()`` does this
    from the operation's owner, or for an unresponsive child from an ancestor's own shutdown body --
    see ``Resource._force_terminal()``), the cancellation is converted to a normal
    restart-unsafe (``is_restart_safe`` ``False``) return *only* when force-terminal evidence was already stored
    before the cancellation was requested. Every joined caller then receives that report rather
    than ``CancelledError``. A cancellation with no pre-recorded evidence is a genuine error and
    propagates normally.
    """
    try:
        coordinator_start = asyncio.get_running_loop().time()

        initialization_pending = await _observe_active_initializer(resource)
        if initialization_pending:
            resource.lifecycle_logger.warning(
                "%s: shutdown proceeding while initialization is still running and did not "
                "observe cancellation -- init and shutdown may now race on shared state",
                resource.unique_name,
            )

        if resource._status not in TERMINAL_STATUSES:
            resource.status = ResourceStatus.STOPPING
        request_shutdown(resource, f"{resource.unique_name} shutdown")

        body_task = create_lifecycle_task(
            resource._shutdown_body(), name=f"resource:shutdown_body:{resource.unique_name}"
        )
        _install_exception_observer(resource, body_task, "shutdown body")
        resource._shutdown_body_task = body_task

        # asyncio.wait, not a bare await: cancelling this coordinator must not cancel the body
        # through the await -- the CancelledError branch below decides that.
        await asyncio.wait([body_task])
        try:
            report = body_task.result()
        except asyncio.CancelledError:  # noqa: ASYNC103 — body cancellation is evidence for this
            # coordinator, not a fatal event for it: convert to SHUTDOWN_BODY_FAILED instead of propagating.
            report = TeardownReport(causes=(TeardownCause.SHUTDOWN_BODY_FAILED,), failed_operations=("_shutdown_body",))
        except Exception:
            resource.lifecycle_logger.exception("Shutdown body for %s raised", resource.unique_name)
            report = TeardownReport(causes=(TeardownCause.SHUTDOWN_BODY_FAILED,), failed_operations=("_shutdown_body",))

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
    except Exception:
        # Anything else escaping the try body (observing the initializer, requesting shutdown,
        # reading a config value) is itself teardown evidence, not a bare crash -- mirrors how
        # a raising shutdown body is turned into SHUTDOWN_BODY_FAILED evidence above rather than
        # left to propagate silently, so the "a completed attempt always produces a report"
        # invariant coordinate_initialize() relies on for its RestartRefusedError guard holds
        # even when the coordinator itself fails outside the body.
        resource.lifecycle_logger.exception("Shutdown coordinator for %s raised", resource.unique_name)
        report = TeardownReport(
            causes=(TeardownCause.COORDINATOR_FAILED,), failed_operations=("_run_shutdown_coordinator",)
        )
        existing = resource._teardown_report
        if existing is not None:
            report = merge_teardown_reports(existing, report)
        resource._teardown_report = report
        raise

    # A retained body task (or a concurrent _force_terminal() call) may already have stored
    # evidence on this attempt (e.g. FORCED_TERMINAL) before this point is reached. Merge
    # rather than overwrite so a later completion can only add evidence, never remove it.
    existing = resource._teardown_report
    if existing is not None:
        report = merge_teardown_reports(existing, report)

    resource.lifecycle_logger.debug(
        "%s: shutdown coordinator completed in %.2fs",
        resource.unique_name,
        elapsed_since(coordinator_start),
    )
    resource._teardown_report = report
    return report


async def coordinate_shutdown(resource: _LifecycleHostP) -> TeardownReport:
    """Coordinator front door for ``shutdown()``.

    Creates ``_shutdown_task`` exactly once per shutdown attempt; every caller (concurrent or
    repeated) shields and awaits that same task, so a repeated call after completion returns
    the stored report without rerunning hooks. Task selection and assignment happen without an
    intervening ``await`` so the check-and-create step is atomic on the event loop.

    A completed ``_shutdown_task`` is reused as-is *unless* ``start()`` has queued a joiner
    (``_pending_start_task``) that has not run ``coordinate_initialize()`` yet -- ``_shutdown_task``
    only gets cleared once that joiner's accepted attempt actually runs (see
    ``coordinate_initialize()``), which can be a full event-loop turn later. Without cancelling
    that joiner here too, this call would return the already-stored clean report while the still-
    queued joiner goes on to initialize the resource behind its back, leaving it running after an
    explicit shutdown already returned. This calls the same ``_cancel_pending_start()`` helper
    ``_observe_active_initializer()`` uses for the *first* shutdown attempt (``_shutdown_task``
    still ``None``) -- but deliberately does not rerun the full coordinator/body: this call has
    already completed and rerunning it would fire ``on_shutdown()`` hooks and emit STOPPED a
    second time, violating this method's own "never reruns hooks" contract above.
    """
    resource = typing.cast("LifecycleMixin", resource)
    reject_lifecycle_reentry(resource, "shutdown")

    task = resource._shutdown_task
    if task is None:
        task = create_lifecycle_task(
            _run_shutdown_coordinator(resource), name=f"resource:shutdown:{resource.unique_name}"
        )
        _install_exception_observer(resource, task, "shutdown coordinator")
        resource._shutdown_task = task
    elif task.done():
        await _cancel_pending_start(resource)

    return await asyncio.shield(task)
