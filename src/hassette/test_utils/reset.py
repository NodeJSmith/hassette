"""Reset utilities for test fixtures.

Provides functions to reset Resource state between tests, enabling module-scoped
fixtures without test pollution.
"""

from typing import TYPE_CHECKING

from hassette.core.app_lifecycle_service import AppAdmissionMode
from hassette.resources.lifecycle import mark_ready
from hassette.test_utils.config import WAIT_FOR_READY_TIMEOUT_SECONDS
from hassette.types.enums import ACTIVE_STATUSES, ResourceStatus

if TYPE_CHECKING:
    from hassette.bus.bus import Bus
    from hassette.config.classes import AppManifest
    from hassette.core.app_handler import AppHandler
    from hassette.core.core import Hassette
    from hassette.core.state_proxy import StateProxy
    from hassette.resources.base import Resource
    from hassette.scheduler.scheduler import Scheduler
    from hassette.test_utils.test_server import SimpleTestServer


async def reset_state_proxy(proxy: "StateProxy", *, require_initial_state_capability: bool = True) -> None:
    """Reset StateProxy to a clean state for testing.

    Performs a full shutdown/initialize cycle so that the proxy and its children
    (Bus, Scheduler) go through proper lifecycle transitions.  The shutdown
    clears the states cache, removes bus listeners, and cancels scheduler jobs.
    The subsequent initialize re-subscribes to events and reloads the cache
    (which will be empty when backed by an AsyncMock API).

    This allows module-scoped fixtures to be reused across tests without
    state pollution.

    Args:
        proxy: The StateProxy instance to reset

    """
    await proxy.shutdown()
    await proxy.initialize()
    generation = proxy.hassette.websocket_service.get_connected_generation()
    if generation is not None:
        if not require_initial_state_capability:
            return
        ready = await proxy.wait_initial_state_capability(timeout=WAIT_FOR_READY_TIMEOUT_SECONDS)
        if not ready:
            raise TimeoutError("Timed out waiting for StateProxy initial state capability during reset")


async def reset_bus(bus: "Bus") -> None:
    """Remove all listeners owned by this bus instance.

    Bus listeners accumulate in the BusService router as tests register handlers.
    This clears them between tests to prevent ordering dependencies. The body is
    synchronous (remove_all_listeners is sync) but the signature remains async
    for interface consistency with sibling reset_* helpers that are awaited
    by HassetteHarness.

    Args:
        bus: The Bus instance to reset.
    """
    bus.remove_all_listeners()


async def reset_scheduler(scheduler: "Scheduler") -> None:
    """Remove all jobs owned by this scheduler instance.

    Jobs persist in the SchedulerService job queue and may fire during subsequent
    tests. This clears them between tests to prevent ordering dependencies.

    Args:
        scheduler: The Scheduler instance to reset.
    """
    await scheduler.remove_all_jobs()


def reset_mock_api(server: "SimpleTestServer") -> None:
    """Clear queued expectations and unexpected request log from the mock server.

    Delegates to ``SimpleTestServer.reset()``.

    Args:
        server: The SimpleTestServer instance to reset.
    """
    server.reset()


async def reset_app_handler(app_handler: "AppHandler", original_manifests: dict[str, "AppManifest"]) -> None:
    """Reset AppHandler to a clean state by re-bootstrapping from a manifest snapshot.

    Performs a full bootstrap cycle: stop all running apps, clear registry state,
    restore manifests from a deep copy, and re-bootstrap. This mirrors the
    framework startup path.

    Args:
        app_handler: The AppHandler instance to reset.
        original_manifests: The post-bootstrap manifest snapshot to restore from.
    """
    for app_key in app_handler.registry.app_keys():
        await app_handler.stop_app(app_key)

    # Clear test-owned listeners before re-bootstrap so they don't fire
    # on APP_LOAD_COMPLETED events during bootstrap_apps().
    app_handler.hassette.bus_service.remove_listeners_by_owner("test")

    app_handler.registry.clear_all()
    app_handler.registry.set_manifests({k: v.model_copy(deep=True) for k, v in original_manifests.items()})
    await app_handler.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)


def _reject_if_active_or_reported(resource: "Resource") -> None:
    """Raise if ``resource`` has an active shutdown task or any stored teardown report.

    Reset is limited to a shutdown request that has never started a teardown attempt — an
    active shutdown task (in progress) or a completed one (a stored report, restart-safe or
    not) both mean a real teardown attempt happened, and this helper must never clear
    that evidence or fabricate a fresh lifecycle state on top of it. In particular, no
    test-only reset may clear a report whose ``is_restart_safe`` is ``False`` — it has no
    in-process reset path, by design.
    """
    if resource._shutdown_task is not None or resource._teardown_report is not None:
        raise RuntimeError(
            f"reset_hassette_lifecycle() cannot reset '{resource.unique_name}': it has an active "
            "shutdown task or a stored teardown report. Reset is limited to a shutdown request "
            "that has not yet started a teardown attempt; construct a fresh instance instead."
        )


def reset_resource_flags(resource: "Resource") -> None:
    """Recursively reset a not-yet-started shutdown request on all descendants of a resource
    (not the resource itself).

    Raises if any descendant has an active shutdown task or a stored teardown report — see
    ``_reject_if_active_or_reported()``. Never clears coordinator fields (``_shutdown_task``,
    ``_shutdown_body_task``, ``_teardown_report``); those are not test-resettable.
    """
    for child in resource.children:
        _reject_if_active_or_reported(child)
        child.shutdown_event.clear()
        reset_resource_flags(child)


async def reset_hassette_lifecycle(hassette: "Hassette", *, original_children: list["Resource"] | None = None) -> None:
    """Clear Hassette's not-yet-started shutdown request for module-scoped fixture reuse.

    This helper is intentionally limited: it only clears an in-flight shutdown *request*
    (``shutdown_event``) that has not yet started a teardown attempt, and marks the instance as
    ready again, optionally restoring the ``children`` list to a previously captured snapshot.
    It does **not** undo the effects of a full ``await hassette.shutdown()`` call (such as
    closed event streams, a stored teardown report, or fully shut-down children) and must not
    be used to revive a Hassette that has been completely shut down.

    Args:
        hassette: The Hassette instance whose shutdown/ready flags should be
            cleared for test-fixture reuse.
        original_children: If provided, restore the children list to this snapshot.

    Raises:
        RuntimeError: If event streams were already closed by a full shutdown, or if the root
            or any descendant has an active shutdown task or a stored teardown report.
    """
    if hassette.event_streams_closed:
        msg = (
            "reset_hassette_lifecycle() cannot be used after a full Hassette "
            "shutdown (event streams are already closed). Create a fresh Hassette "
            "instance instead."
        )
        raise RuntimeError(msg)

    _reject_if_active_or_reported(hassette)

    hassette.shutdown_event.clear()
    hassette._fatal_shutdown_reason = None
    mark_ready(hassette, reason="reset for test")
    if original_children is not None:
        hassette.children[:] = original_children

    # Reset _status to RUNNING via the ._status bypass so that subsequent calls to
    # hassette.shutdown() in the next test see RUNNING → STOPPING, which is a valid
    # transition.  Without this reset, a previous test's hassette.shutdown() would
    # leave status=STOPPED; the next test's shutdown() would attempt STOPPED → STOPPING,
    # which is invalid under strict lifecycle mode.
    if hassette._status not in ACTIVE_STATUSES:
        hassette._status = ResourceStatus.RUNNING

    reset_resource_flags(hassette)
