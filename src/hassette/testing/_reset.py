"""Reset utilities for test fixtures.

Provides functions to reset Resource state between tests, enabling module-scoped
fixtures without test pollution.
"""

from typing import TYPE_CHECKING

from hassette_wire import ResourceStatus

from hassette.core.app_lifecycle_common import AppAdmissionMode
from hassette.resources.lifecycle import mark_ready
from hassette.testing.config import WAIT_FOR_READY_TIMEOUT_SECONDS
from hassette.types.enums import ACTIVE_STATUSES

if TYPE_CHECKING:
    from hassette.config.classes import AppManifest
    from hassette.core.app_handler import AppHandler
    from hassette.core.core import Hassette
    from hassette.core.integration_service import IntegrationService
    from hassette.core.state_proxy import StateProxy
    from hassette.resources.base import Resource
    from hassette.scheduler.scheduler import Scheduler


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
        require_initial_state_capability: When the websocket is connected, wait for the proxy's
            initial state capability after re-initializing (raising ``TimeoutError`` if it never
            arrives). Pass ``False`` to skip the wait.

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


def reset_integration(service: "IntegrationService") -> None:
    """Forget every committed entity and owner and zero the entity revision.

    A harness's in-memory integration service keeps what one test committed until this runs, so the next
    test on a shared harness would otherwise see its entities. ``boot_id`` stays: it identifies the service
    instance, which survives the reset.

    Args:
        service: The IntegrationService to reset.
    """
    service._entities.clear()
    service._owners.clear()
    service.entity_revision = 0


async def reset_scheduler(scheduler: "Scheduler") -> None:
    """Remove all jobs owned by this scheduler instance.

    Jobs persist in the SchedulerService job queue and may fire during subsequent
    tests. This clears them between tests to prevent ordering dependencies.

    Args:
        scheduler: The Scheduler instance to reset.
    """
    await scheduler.remove_all_jobs()


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
    """Raise if ``resource`` has an active shutdown task or any stored shutdown outcome.

    Reset is limited to a shutdown request that has never started a teardown attempt — an
    active shutdown task (in progress) or a completed one (a stored outcome, restart-safe or
    not) both mean a real teardown attempt happened, and this helper must never clear
    that evidence or fabricate a fresh lifecycle state on top of it. In particular, no
    test-only reset may clear an outcome whose ``is_restart_safe`` is ``False`` — it has no
    in-process reset path, by design.
    """
    if resource._shutdown_task is not None or resource._shutdown_outcome is not None:
        raise RuntimeError(
            f"reset_hassette_lifecycle() cannot reset '{resource.unique_name}': it has an active "
            "shutdown task or a stored shutdown outcome. Reset is limited to a shutdown request "
            "that has not yet started a teardown attempt; construct a fresh instance instead."
        )


def _reject_tree_if_active_or_reported(resource: "Resource") -> None:
    """Validate ``resource`` and every current descendant before any shutdown/ready state is mutated.

    ``reset_hassette_lifecycle()`` calls this on the whole tree after restoring ``children`` to
    an ``original_children`` snapshot (if given) but before clearing ``shutdown_event`` or any
    other state. The whole tree is validated before any resource is mutated, so a failing
    descendant cannot leave the tree half-reset. Validating the restored tree means test-added
    children that ``original_children`` discards never block a reset.
    """
    _reject_if_active_or_reported(resource)
    for child in resource.children:
        _reject_tree_if_active_or_reported(child)


def reset_resource_flags(resource: "Resource") -> None:
    """Recursively reset a not-yet-started shutdown request on all descendants of a resource.

    The resource itself is not reset.

    Does not validate: the caller must run ``_reject_tree_if_active_or_reported()`` on the whole
    tree first, so a failing descendant cannot leave the tree half-reset. Never clears coordinator fields
    (``_shutdown_task``, ``_shutdown_body_task``, ``_shutdown_outcome``); those are not
    test-resettable.
    """
    for child in resource.children:
        child.shutdown_event.clear()
        reset_resource_flags(child)


async def reset_hassette_lifecycle(hassette: "Hassette", *, original_children: list["Resource"] | None = None) -> None:
    """Clear Hassette's not-yet-started shutdown request for module-scoped fixture reuse.

    This helper is intentionally limited: it only clears an in-flight shutdown *request*
    (``shutdown_event``) that has not yet started a teardown attempt, and marks the instance as
    ready again, optionally restoring the ``children`` list to a previously captured snapshot.
    It does **not** undo the effects of a full ``await hassette.shutdown()`` call (such as
    closed event streams, a stored shutdown outcome, or fully shut-down children) and must not
    be used to revive a Hassette that has been completely shut down.

    Args:
        hassette: The Hassette instance whose shutdown/ready flags should be
            cleared for test-fixture reuse.
        original_children: If provided, restore the children list to this snapshot before
            validating the tree -- so a test that dynamically added its own children (e.g.
            dummy services) can still reset even if those now-discarded children have an
            active shutdown task or a stored shutdown outcome.

    Raises:
        RuntimeError: If event streams were already closed by a full shutdown, or if the root
            or any descendant has an active shutdown task or a stored shutdown outcome.
    """
    if hassette.event_streams_closed:
        msg = (
            "reset_hassette_lifecycle() cannot be used after a full Hassette "
            "shutdown (event streams are already closed). Create a fresh Hassette "
            "instance instead."
        )
        raise RuntimeError(msg)

    # Restore the children snapshot (if given) *before* validating the tree, not after -- a
    # test that dynamically added its own children (e.g. dummy services registered directly
    # under `hassette`) is exactly what this snapshot exists to discard. Those children are
    # about to be dropped from the tree entirely, so their own shutdown/outcome state is
    # irrelevant to whether reset can proceed; validating before the restore would reject a
    # reset the caller can perfectly well do, over state that is about to become unreachable
    # anyway.
    if original_children is not None:
        hassette.children[:] = original_children

    _reject_tree_if_active_or_reported(hassette)

    hassette.shutdown_event.clear()
    hassette._fatal_shutdown_reason = None
    mark_ready(hassette, reason="reset for test")

    # Reset _status to RUNNING via the ._status bypass so that subsequent calls to
    # hassette.shutdown() in the next test see RUNNING → STOPPING, which is a valid
    # transition.  Without this reset, a previous test's hassette.shutdown() would
    # leave status=STOPPED; the next test's shutdown() would attempt STOPPED → STOPPING,
    # which is invalid under strict lifecycle mode.
    if hassette._status not in ACTIVE_STATUSES:
        hassette._status = ResourceStatus.RUNNING

    reset_resource_flags(hassette)
