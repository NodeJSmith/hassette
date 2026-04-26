"""Reset utilities for test fixtures.

Provides functions to reset Resource state between tests, enabling module-scoped
fixtures without test pollution.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hassette.bus.bus import Bus
    from hassette.config.classes import AppManifest
    from hassette.core.app_handler import AppHandler
    from hassette.core.core import Hassette
    from hassette.core.state_proxy import StateProxy
    from hassette.resources.base import Resource
    from hassette.scheduler.scheduler import Scheduler
    from hassette.test_utils.test_server import SimpleTestServer


async def reset_state_proxy(proxy: "StateProxy") -> None:
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

    Example:
        >>> async def cleanup_state_proxy(proxy: StateProxy):
        ...     await reset_state_proxy(proxy)
    """
    await proxy.shutdown()
    await proxy.initialize()


async def reset_bus(bus: "Bus") -> None:
    """Remove all listeners owned by this bus instance.

    Bus listeners accumulate in the BusService router as tests register handlers.
    This clears them between tests to prevent ordering dependencies.

    Args:
        bus: The Bus instance to reset.
    """
    await bus.remove_all_listeners()


async def reset_scheduler(scheduler: "Scheduler") -> None:
    """Remove all jobs owned by this scheduler instance.

    Jobs persist in the SchedulerService job queue and may fire during subsequent
    tests. This clears them between tests to prevent ordering dependencies.

    Args:
        scheduler: The Scheduler instance to reset.
    """
    await scheduler._remove_all_jobs()


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
    for app_key in list(app_handler.registry.apps):
        await app_handler.stop_app(app_key)

    # Clear test-owned listeners before re-bootstrap so they don't fire
    # on APP_LOAD_COMPLETED events during bootstrap_apps().
    await app_handler.hassette.bus_service.remove_listeners_by_owner("test")

    app_handler.registry.clear_all()
    app_handler.registry.set_manifests({k: v.model_copy(deep=True) for k, v in original_manifests.items()})
    await app_handler.lifecycle.bootstrap_apps()


def _reset_resource_flags(resource: "Resource") -> None:
    """Recursively reset lifecycle flags on all descendants of a resource (not the resource itself)."""
    for child in resource.children:
        child._shutdown_completed = False
        child._shutting_down = False
        child.shutdown_event.clear()
        _reset_resource_flags(child)


async def reset_hassette_lifecycle(hassette: "Hassette", *, original_children: list["Resource"] | None = None) -> None:
    """Clear Hassette shutdown/ready flags for module-scoped fixture reuse.

    This helper is intentionally limited: it only clears an in-flight shutdown
    request and marks the instance as ready again, optionally restoring the
    ``children`` list to a previously captured snapshot. It does **not** undo the
    effects of a full ``await hassette.shutdown()`` call (such as closed event
    streams or fully shut-down children) and must not be used to revive a
    Hassette that has been completely shut down.

    Args:
        hassette: The Hassette instance whose shutdown/ready flags should be
            cleared for test-fixture reuse.
        original_children: If provided, restore the children list to this snapshot.

    Raises:
        RuntimeError: If event streams were already closed by a full shutdown.
    """
    if hassette.event_streams_closed:
        msg = (
            "reset_hassette_lifecycle() cannot be used after a full Hassette "
            "shutdown (event streams are already closed). Create a fresh Hassette "
            "instance instead."
        )
        raise RuntimeError(msg)

    hassette.shutdown_event.clear()
    hassette._shutting_down = False
    hassette._shutdown_completed = False
    hassette.mark_ready(reason="reset for test")
    if original_children is not None:
        hassette.children[:] = original_children

    _reset_resource_flags(hassette)
