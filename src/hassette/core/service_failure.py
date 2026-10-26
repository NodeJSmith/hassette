"""Routing for a service's failure after its handoff to ``serve()`` (spec 134 D8, D14).

Nothing on the report path awaits; the CRASHED event send is spawned, not awaited.
"""

import typing

from hassette_wire import ResourceStatus

from hassette.events import HassetteServiceEvent
from hassette.exceptions import ServeEndedError
from hassette.resources.lifecycle import request_shutdown

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette
    from hassette.resources.service import Service


def route_service_failure(hassette: "Hassette", service: "Service", exc: BaseException) -> None:
    """Route a reported failure: a required service's ends the process, an optional one's gets one ERROR.

    A report arriving once shutdown was requested, or once a fatal reason is latched, is logged and not
    escalated, so a clean stop still exits 0. A failed optional service is left dead in place.
    """
    if hassette.shutdown_event.is_set() or hassette.fatal_shutdown_reason is not None:
        hassette.logger.error(
            "%s '%s' failed after shutdown began or a fatal error was recorded, not escalating: %s: %s",
            service.role,
            service.class_name,
            type(exc).__name__,
            exc,
        )
        return
    if service.required:
        escalate_service_failure(hassette, service, exc)
        return
    serve_task = service._optional_serve_task()
    serve_task_name = serve_task.get_name() if serve_task is not None else None
    pending = [name for name in service.task_bucket.pending_task_names() if name != serve_task_name]
    recovery = "a hassette restart" if service.parent is hassette else "reloading the app that owns it"
    hassette.logger.error(
        "Optional %s '%s' failed and stays down until %s brings it back (%s: %s); pending tasks: %s",
        service.role,
        service.unique_name,
        recovery,
        type(exc).__name__,
        exc,
        ", ".join(pending) or "none",
    )


def escalate_service_failure(hassette: "Hassette", service: "Service", exc: BaseException) -> None:
    """End the process for a required service's failure: the one fatal exit route (spec 134 D14).

    Records the fatal reason in memory, requests shutdown so ``run_forever()`` owns the exit, and
    emits CRASHED as telemetry without awaiting it, so neither the bus nor the database can delay
    the exit. CRASHED here means "took the process down": the service's own status is still FAILED
    unless it raised a ``FatalError``. Teardown's session finalize writes the reason to the session
    record, best-effort.
    """
    if isinstance(exc, ServeEndedError):
        reason = f"{service.role} '{service.class_name}' serve() ended without shutdown"
    else:
        reason = f"{service.role} '{service.class_name}' crashed: {type(exc).__name__}"
    hassette.logger.error("%s, shutting down Hassette: %s", reason, exc)
    hassette.record_fatal_reason(reason)
    request_shutdown(hassette, reason)
    event = HassetteServiceEvent.from_service_status(
        resource_name=service.class_name,
        role=service.role,
        status=ResourceStatus.CRASHED,
        previous_status=service.status,
        exception=exc,
    )
    try:
        hassette.task_bucket.spawn(
            send_crashed_event(hassette, event), name=f"hassette:crashed_event:{service.class_name}"
        )
    except Exception as spawn_exc:
        hassette.logger.debug("Could not emit CRASHED for %s: %s", service.class_name, spawn_exc)


async def send_crashed_event(hassette: "Hassette", event: HassetteServiceEvent) -> None:
    """Send a CRASHED telemetry event, best-effort: teardown may cancel it, and a failed send is not an error."""
    try:
        await hassette.send_event(event)
    except Exception as exc:
        hassette.logger.debug("CRASHED event for %s not sent: %s", event.payload.data.resource_name, exc)
