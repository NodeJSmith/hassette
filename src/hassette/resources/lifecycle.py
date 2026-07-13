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

import typing

from hassette.events import HassetteServiceEvent
from hassette.resources.mixins import LifecycleMixin, _LifecycleHostP
from hassette.types.enums import TERMINAL_STATUSES, ResourceStatus


def create_service_status_event(
    resource: _LifecycleHostP,
    status: ResourceStatus,
    exception: Exception | BaseException | None = None,
    ready: bool = False,
    ready_phase: str | None = None,
) -> HassetteServiceEvent:
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
    """Start the instance by spawning its initialize method in a task."""
    resource = typing.cast("LifecycleMixin", resource)
    resource.shutdown_completed = False

    if resource._init_task and not resource._init_task.done():
        resource.logger.debug("%s already started or running", resource.unique_name, stacklevel=2)
        return

    resource.logger.debug("%s starting", resource.unique_name)
    resource._init_task = resource.task_bucket.spawn(resource.initialize(), name="resource:resource_initialize")


def cancel(resource: _LifecycleHostP) -> None:
    """Cancel the main task of the instance, if it is running."""
    resource = typing.cast("LifecycleMixin", resource)
    if resource._init_task and not resource._init_task.done():
        resource._init_task.cancel()
        resource.logger.debug("%s cancelled task", resource.unique_name)
        return

    resource.logger.debug("%s no running task to cancel", resource.unique_name)


async def handle_stop(resource: _LifecycleHostP) -> None:
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
