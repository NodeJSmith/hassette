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
import dataclasses
import threading
import typing
from contextlib import suppress
from typing import Any

from hassette.events import HassetteServiceEvent
from hassette.exceptions import LifecycleReentryError, RestartRefusedError
from hassette.resources.mixins import LifecycleMixin, _LifecycleHostP
from hassette.resources.teardown import (
    TeardownCause,
    TeardownReport,
    add_teardown_evidence,
    merge_teardown_reports,
)
from hassette.types.enums import TERMINAL_STATUSES, ResourceStatus

if typing.TYPE_CHECKING:
    from collections.abc import Coroutine


COORDINATOR_MARGIN_FRACTION = 0.1
"""Fraction of the total shutdown timeout reserved as a gap between the body's own
deadline and the coordinator's outer ``asyncio.wait()`` bound. Guarantees the body
finishes (and its result is observed) before the coordinator abandons it — replacing
the former ``ROOT_SHUTDOWN_BODY_TIMEOUT_FRACTION`` and the ``HOOK_BUDGET_FRACTION``
margin that each addressed the same race from different directions."""

TASK_CANCEL_SECONDS = 1.0
"""Fixed budget for ``_run_task_bucket_shutdown_stage()``. Replaces the former
``CANCEL_BUDGET_FRACTION`` (20% of shrinking remainder)."""

CLEANUP_SECONDS = 0.5
"""Fixed budget for ``cleanup()``. Replaces the former ``CLEANUP_BUDGET_FRACTION``
(50% of shrinking remainder)."""

CHILDREN_FLOOR_SECONDS = 1.0
"""Minimum guaranteed budget for ``_shutdown_children()``. Unchanged from the former
``CHILDREN_SHUTDOWN_BUDGET_FLOOR_SECONDS`` — the floor concept is preserved, but now
children also benefit from any slack the hooks pool didn't use."""

HOOKS_FLOOR_SECONDS = 0.5
"""Minimum guaranteed budget for hooks/serve-wait/initializer observation, even when the
total timeout is too small to fit the full tail reservation. Without this floor, any
``resource_shutdown_timeout_seconds`` at or below ``(TASK_CANCEL_SECONDS + CLEANUP_SECONDS +
CHILDREN_FLOOR_SECONDS + HOOKS_FLOOR_SECONDS) / (1 - COORDINATOR_MARGIN_FRACTION)`` (~3.33s
with defaults) would compute a zero-length hooks pool, so ``on_shutdown()`` (and every other
shutdown hook) would be cancelled at its first suspension point regardless of how little work
it does. ``LifecycleConfig`` places no lower bound on ``resource_shutdown_timeout_seconds``,
so this floor is reachable in practice."""


@dataclasses.dataclass(frozen=True)
class ShutdownBudget:
    """Pre-computed budget allocation for a single shutdown attempt.

    Computed once by ``compute_shutdown_budget()`` at the top of
    ``_run_shutdown_coordinator()`` and stored on the resource. Each stage reads its
    own field directly — no stage derives its budget from "what's left of a shrinking
    remainder."

    The ``hooks_pool_deadline`` is the one place where sequential "remaining" logic
    still applies: hooks run sequentially and each gets whatever remains of the pool.
    The pool itself is a fixed allocation from the total, so compounding within it
    cannot starve the mandatory tail (task cancel, cleanup, children).
    """

    hooks_pool_deadline: float
    """Absolute loop time by which all hooks, serve-wait, and initializer observation
    must finish. Each consumer reads ``max(0, hooks_pool_deadline - loop.time())``."""

    task_cancel_seconds: float
    """Fixed duration for ``_run_task_bucket_shutdown_stage()``."""

    cleanup_seconds: float
    """Fixed duration for ``cleanup()``."""

    children_floor_seconds: float
    """Minimum guaranteed duration for ``_shutdown_children()``."""

    body_deadline: float
    """Absolute loop time by which the entire ``_shutdown_body()`` must finish.
    Children get ``max(children_floor_seconds, body_deadline - loop.time())``
    after task-cancel and cleanup have run — so early-finishing hooks pass their
    slack to children naturally. Also the deadline the root's own
    ``Hassette._shutdown_body()`` bounds itself with internally, via its own
    ``asyncio.timeout()`` -- deliberately *tighter* than ``total_deadline`` below so its
    graceful ``TOTAL_TIMEOUT``/stream-closing fallback gets a chance to run before the
    coordinator's cruder outer force-cancel does."""

    total_deadline: float
    """Absolute loop time by which the coordinator's own outer wait on the whole shutdown
    body task gives up -- ``now + total_seconds`` from ``compute_shutdown_budget()``,
    *not* reduced by ``COORDINATOR_MARGIN_FRACTION`` the way ``body_deadline`` is. This is
    what ``_run_shutdown_coordinator()``'s outer ``asyncio.wait()`` bound reads (via
    ``total_deadline_remaining()``): using ``body_deadline`` there instead would collapse
    the margin gap this budget exists to create, racing the coordinator's blunt cancel
    against the body's own graceful internal deadline instead of only backstopping it.
    Using the fixed ``total_seconds`` again (rather than measuring afresh from whenever the
    outer wait happens to start) is what keeps a shutdown attempt whose
    initializer-observation phase already spent real time from this same budget bounded to
    the *original* configured timeout instead of that time plus a full timeout again."""


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
    """
    resource = typing.cast("LifecycleMixin", resource)

    loop_thread_id = resource.hassette.loop_thread_id
    if loop_thread_id is not None and threading.get_ident() != loop_thread_id:

        def _start_on_loop_thread() -> None:
            try:
                start(resource)
            except Exception:
                resource.logger.exception(
                    "%s: cross-thread start() failed after re-dispatch onto the loop thread",
                    resource.unique_name,
                )

        resource.hassette.loop.call_soon_threadsafe(_start_on_loop_thread)
        return

    reject_lifecycle_reentry(resource, "start")

    if resource._init_task is not None and not resource._init_task.done():
        resource.logger.debug("%s already started or running", resource.unique_name, stacklevel=2)
        return

    # A second guard, not a duplicate of the one above: _init_task is only assigned once the
    # joiner below actually runs coordinate_initialize(), which can be a turn or more later.
    # Without this check, a second start() call issued before that first turn would see
    # _init_task still None and spawn a second, redundant joiner. See _pending_start_task's
    # docstring for the shutdown-race this same field also closes.
    if resource._pending_start_task is not None and not resource._pending_start_task.done():
        resource.logger.debug("%s start already pending", resource.unique_name, stacklevel=2)
        return

    report = resource._teardown_report
    if report is not None and not report.is_restart_safe:
        raise RestartRefusedError(resource.unique_name, report)

    resource.logger.debug("%s starting", resource.unique_name)
    joiner = create_lifecycle_task(resource.initialize(), name="resource:resource_initialize")
    _install_exception_observer(resource, joiner, "start joiner")
    resource._pending_start_task = joiner

    def _clear_pending_start(task: asyncio.Task) -> None:
        if resource._pending_start_task is task:
            resource._pending_start_task = None

    joiner.add_done_callback(_clear_pending_start)


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
                resource.logger.exception(
                    "%s: cross-thread cancel() failed after re-dispatch onto the loop thread",
                    resource.unique_name,
                )

        resource.hassette.loop.call_soon_threadsafe(_cancel_on_loop_thread)
        return

    cancelled_something = False

    if resource._pending_start_task is not None and not resource._pending_start_task.done():
        resource._pending_start_task.cancel()
        resource.logger.debug("%s cancelled pending start joiner", resource.unique_name)
        cancelled_something = True

    if resource._init_task and not resource._init_task.done():
        resource._init_task.cancel()
        resource.logger.debug("%s cancelled task", resource.unique_name)
        cancelled_something = True

    if not cancelled_something:
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


def is_teardown_confirmed_quiescent(resource: _LifecycleHostP) -> bool:
    """Return True if nothing tracked from the resource's (or any descendant's) last teardown
    attempt is still running.

    Checks the resource's task_bucket for any pending task names, its shutdown-body task (if any)
    for completion, and ``_has_untracked_teardown_work_pending()`` (for lifecycle-owned work that
    deliberately bypasses TaskBucket, e.g. ``DatabaseService._db_worker_task``), then recurses into
    ``resource.children`` -- matching the granularity of the classification that gates this check:
    ``TeardownReport.is_timeout_only_refusal`` is computed over a report that already folds in
    every child's causes (see ``shutdown_batch()``/``finalize_shutdown_report()`` in
    ``operations.py``), so a service with a child resource (e.g. ``WebApiService``'s ``Scheduler``)
    must have its confirmation checked at the same subtree scope or a recoverable timeout in the
    child would never be confirmable. All of this reflects *live* state, not a frozen snapshot from
    when a TeardownReport was generated -- every tracked task is discarded from its bucket the
    moment it actually finishes (see TaskBucket's done-callback in task_bucket.py), and
    ``_shutdown_body_task`` is never reset to None, so this can be polled safely at any point after
    teardown to confirm -- rather than assume -- that a timeout-only refusal has actually resolved.
    """
    resource = typing.cast("LifecycleMixin", resource)
    body_task = resource._shutdown_body_task
    if (
        resource.task_bucket.pending_task_names()
        or (body_task is not None and not body_task.done())
        or resource._has_untracked_teardown_work_pending()
    ):
        return False
    return all(is_teardown_confirmed_quiescent(child) for child in resource.children)


def _collect_forced_descendant_evidence(
    resource: "LifecycleMixin",
) -> "tuple[list[TeardownReport], list[str]]":
    """Recursively collect every descendant's own teardown report that is not restart-safe.

    Unlike the normal ``shutdown_batch()``/``finalize_shutdown_report()`` path -- where each
    level's own report already rolls up its children because a graceful ``shutdown()`` call
    itself recurses through ``_shutdown_children()`` -- a ``_force_terminal()`` cascade only
    records each level's own task-bucket evidence on that level's own report; it never folds a
    child's outcome into its parent's. Called after ``resource._force_terminal()`` so every
    descendant's report already reflects that cascade.
    """
    reports: list[TeardownReport] = []
    affected: list[str] = []
    for child in resource.children:
        child_report = child._teardown_report
        if child_report is not None and not child_report.is_restart_safe:
            reports.append(child_report)
            affected.append(child.unique_name)
        nested_reports, nested_affected = _collect_forced_descendant_evidence(child)
        reports.extend(nested_reports)
        affected.extend(nested_affected)
    return reports, affected


def create_lifecycle_task(coro: "Coroutine[Any, Any, Any]", *, name: str) -> asyncio.Task:
    """Create a lifecycle-owned task outside TaskBucket ownership.

    Not module-private despite the plain name -- ``Resource._shutdown_children()`` (base.py)
    and ``Hassette._shutdown_children()`` (core.py) also use this to create each child's
    ``shutdown()`` task, for the same reason the coordinator/body tasks below need it: those
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


def compute_shutdown_budget(
    total_seconds: float, now: float, task_cancel_ceiling: float = TASK_CANCEL_SECONDS
) -> ShutdownBudget:
    """Allocate shutdown time across stages up front, from the total.

    Called once per shutdown attempt. The allocation is:

    1. ``COORDINATOR_MARGIN_FRACTION`` of total reserved for the coordinator/body gap.
    2. ``task_cancel_ceiling`` (normally ``lifecycle.task_cancellation_timeout_seconds``)
       + ``CLEANUP_SECONDS`` + ``CHILDREN_FLOOR_SECONDS`` reserved for the mandatory tail.
    3. Everything else becomes the hooks pool (hooks, serve-wait, initializer observation).

    If the total is too small to fit the full tail reservation plus ``HOOKS_FLOOR_SECONDS``,
    every stage — hooks included — scales down proportionally instead of the hooks pool
    dropping to 0. A resource with a configured timeout too small to fit any of this ends up
    with a proportionally tiny but still nonzero share for every stage.
    """
    tail_reservation = task_cancel_ceiling + CLEANUP_SECONDS + CHILDREN_FLOOR_SECONDS
    full_reservation = tail_reservation + HOOKS_FLOOR_SECONDS

    margin = total_seconds * COORDINATOR_MARGIN_FRACTION
    body_budget = total_seconds - margin

    if body_budget >= full_reservation:
        hooks_pool = body_budget - tail_reservation
        task_cancel = task_cancel_ceiling
        cleanup = CLEANUP_SECONDS
        children_floor = CHILDREN_FLOOR_SECONDS
    else:
        scale = body_budget / full_reservation if full_reservation > 0 else 0.0
        hooks_pool = HOOKS_FLOOR_SECONDS * scale
        task_cancel = task_cancel_ceiling * scale
        cleanup = CLEANUP_SECONDS * scale
        children_floor = CHILDREN_FLOOR_SECONDS * scale

    return ShutdownBudget(
        hooks_pool_deadline=now + hooks_pool,
        task_cancel_seconds=task_cancel,
        cleanup_seconds=cleanup,
        children_floor_seconds=children_floor,
        body_deadline=now + body_budget,
        total_deadline=now + total_seconds,
    )


def hooks_pool_remaining(resource: _LifecycleHostP) -> float:
    """Seconds left in the hooks pool for the current shutdown attempt.

    Used by ``run_hooks()`` (each hook), the serve-task wait, and
    ``_observe_active_initializer()`` — everything that shares the discretionary pool.
    Returns ``resource_shutdown_timeout_seconds`` when no budget has been set yet (the
    coordinator always sets one before any consumer runs; this is a defensive fallback,
    not the normal path), and 0 only once the pool itself is exhausted.
    """
    resource = typing.cast("LifecycleMixin", resource)
    budget = resource._shutdown_budget
    if budget is None:
        return resource.hassette.config.lifecycle.resource_shutdown_timeout_seconds
    return max(0.0, budget.hooks_pool_deadline - asyncio.get_running_loop().time())


def children_budget_remaining(resource: _LifecycleHostP) -> float:
    """Seconds available for ``_shutdown_children()``.

    Children run last and benefit from any slack the earlier stages left behind.
    Returns at least ``children_floor_seconds`` even when the body is over budget.
    """
    resource = typing.cast("LifecycleMixin", resource)
    budget = resource._shutdown_budget
    if budget is None:
        return resource.hassette.config.lifecycle.resource_shutdown_timeout_seconds
    return max(budget.children_floor_seconds, budget.body_deadline - asyncio.get_running_loop().time())


def total_deadline_remaining(resource: _LifecycleHostP) -> float:
    """Seconds left until the coordinator's own outer wait on the shutdown body gives up.

    Used by ``_run_shutdown_coordinator()``'s outer ``asyncio.wait()`` bound on the body
    task. Deliberately reads ``total_deadline`` (the *un*-margin-reduced deadline), not
    ``body_deadline`` -- the outer wait is meant to be the coordinator's last-resort
    backstop, strictly looser than the body's own internal deadline (e.g. the root's
    ``Hassette._shutdown_body()`` bounds itself with ``body_deadline``, deliberately
    tighter, so its graceful ``TOTAL_TIMEOUT`` fallback gets a chance to run first). Also
    what keeps a shutdown attempt whose initializer-observation phase already spent real
    time from the same budget bounded to the original configured timeout, rather than that
    time plus a full timeout again. Returns ``resource_shutdown_timeout_seconds`` when no
    budget has been set yet, and 0 once the deadline has already passed.
    """
    resource = typing.cast("LifecycleMixin", resource)
    budget = resource._shutdown_budget
    if budget is None:
        return resource.hassette.config.lifecycle.resource_shutdown_timeout_seconds
    return max(0.0, budget.total_deadline - asyncio.get_running_loop().time())


def elapsed_since(start: float) -> float:
    """Seconds elapsed since ``start``, an ``asyncio.get_running_loop().time()`` snapshot.

    Shared by every shutdown-stage timing log (waves, task-bucket cancel, cleanup,
    child propagation, initializer observation, shutdown-body wait, and the coordinator
    itself) so each stage measures its own span with one line instead of repeating the
    subtraction.
    """
    return asyncio.get_running_loop().time() - start


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
    if report is not None and not report.is_restart_safe:
        raise RestartRefusedError(resource.unique_name, report)

    init_task = resource._init_task
    if init_task is None or init_task.done():
        if resource._teardown_report is not None:
            # First accepted initialization after a clean (SAFE) teardown: consume the report
            # and reopen the resources that a completed shutdown attempt sealed/cleared.
            resource._teardown_report = None
            resource._shutdown_task = None
            resource._shutdown_hooks_completed = False
            resource.task_bucket.reopen()
            resource.shutdown_event.clear()
        init_task = create_lifecycle_task(
            resource._initialize_body(), name=f"resource:initialize:{resource.unique_name}"
        )
        _install_exception_observer(resource, init_task, "initialization coordinator")
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
    timeout = hooks_pool_remaining(resource)
    observe_start = asyncio.get_running_loop().time()
    _done, pending = await asyncio.wait([init_task], timeout=timeout)
    resource.logger.debug(
        "%s: initializer observation completed in %.2fs (budget %.2fs)",
        resource.unique_name,
        elapsed_since(observe_start),
        timeout,
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

    Cancels and observes an active initializer, transitions status and requests shutdown,
    then bounds observation of the class-specific ``_shutdown_body()`` for
    ``resource_shutdown_timeout_seconds``. Stores and returns the merged report.

    If something external cancels this coordinator task directly (``_force_terminal()`` may do
    this for an unresponsive child from an ancestor's own shutdown body -- see
    ``Resource._force_terminal()``), the cancellation is converted to a normal
    restart-unsafe (``is_restart_safe`` ``False``) return *only* when force-terminal evidence was already stored
    before the cancellation was requested. Every joined caller then receives that report rather
    than ``CancelledError``. A cancellation with no pre-recorded evidence is a genuine error and
    propagates normally.
    """
    try:
        if typing.cast("object", resource) is resource.hassette:
            timeout = resource.hassette.config.lifecycle.total_shutdown_timeout_seconds
        else:
            timeout = resource.hassette.config.lifecycle.resource_shutdown_timeout_seconds

        coordinator_start = asyncio.get_running_loop().time()
        task_cancel_ceiling = resource.hassette.config.lifecycle.task_cancellation_timeout_seconds
        resource._shutdown_budget = compute_shutdown_budget(timeout, coordinator_start, task_cancel_ceiling)

        initialization_pending = await _observe_active_initializer(resource)
        if initialization_pending:
            resource.logger.warning(
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

        # Uses the remaining time to the un-margin-reduced total deadline (now0 + timeout),
        # not a fresh `timeout` measured from whenever this wait happens to start -- that would
        # let a single shutdown attempt run up to (time _observe_active_initializer() already
        # spent above, part of the same hooks pool) + a full timeout again. Deliberately not
        # `body_deadline` either: that deadline is margin-reduced and is what the body's own
        # internal logic (e.g. Hassette._shutdown_body()'s TOTAL_TIMEOUT fallback) bounds itself
        # with, so it gets a chance to finish gracefully before this cruder outer backstop fires.
        wait_timeout = total_deadline_remaining(resource)
        body_wait_start = asyncio.get_running_loop().time()
        done, _pending = await asyncio.wait([body_task], timeout=wait_timeout)
        body_wait_elapsed = elapsed_since(body_wait_start)

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
            resource.logger.debug("%s: shutdown body completed in %.2fs", resource.unique_name, body_wait_elapsed)
        else:
            resource.logger.warning(
                "%s shutdown body did not complete within its %.2fs deadline (%.2fs configured timeout, %.2fs elapsed)",
                resource.unique_name,
                wait_timeout,
                timeout,
                body_wait_elapsed,
            )
            report = TeardownReport(causes=(TeardownCause.SHUTDOWN_BODY_TIMED_OUT,))
            # record_cause tracks whether the body's shutdown hooks (before_shutdown/on_shutdown/
            # after_shutdown -- where most resources release what they hold) already ran to
            # completion *without raising*. If they did, _force_terminal()'s cascade only cuts
            # short task-bucket cancellation/cleanup()/child propagation, each of which already
            # produces its own evidence through the normal paths -- adding FORCED_TERMINAL on top
            # would only push this report outside TIMEOUT_ONLY_CAUSES and make
            # is_timeout_only_refusal unreachable for this path. If they did NOT run cleanly --
            # never got a chance to run, or one of them raised -- _force_terminal() skips them for
            # good (it never calls on_shutdown() itself) and a raised hook's own evidence would
            # otherwise be lost when this cancelled body never returns it, so whatever that
            # resource holds may never be released for the rest of the process's life -- record
            # FORCED_TERMINAL for real so this escalates instead of silently degrading. See
            # _shutdown_hooks_completed's docstring (mixins.py).
            resource._force_terminal(record_cause=not resource._shutdown_hooks_completed)
            # _force_terminal() cascades into every descendant (each stamped FORCED_TERMINAL on
            # its own report), but the abandoned body never reached its own _shutdown_children()
            # stage -- the only place that normally folds a child's outcome into the parent's
            # report (see shutdown_batch()/finalize_shutdown_report() in operations.py). Without
            # this, a resource with force-terminated, hook-skipped children could still classify
            # as is_timeout_only_refusal and degrade instead of escalating.
            descendant_reports, unsafe_descendants = _collect_forced_descendant_evidence(resource)
            if unsafe_descendants:
                report = merge_teardown_reports(report, *descendant_reports)
                report = add_teardown_evidence(
                    report, causes=(TeardownCause.CHILD_RESTART_UNSAFE,), affected_resources=tuple(unsafe_descendants)
                )
            if not body_task.done():
                body_task.cancel()
                # No separate SHUTDOWN_BODY_PENDING cause -- this branch is reached only when the
                # body already timed out (SHUTDOWN_BODY_TIMED_OUT, above), and no suspension point
                # separates the two checks, so a second cause here would record the same fact
                # twice under two names. pending_tasks alone carries the "still alive right now"
                # detail.
                report = add_teardown_evidence(report, pending_tasks=(body_task.get_name(),))

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
        resource.logger.exception("Shutdown coordinator for %s raised", resource.unique_name)
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

    resource.logger.debug(
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
