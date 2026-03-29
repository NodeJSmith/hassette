"""Reset utilities for test fixtures.

Provides functions to reset Resource state between tests, enabling module-scoped
fixtures without test pollution.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hassette.bus.bus import Bus
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
    await scheduler.remove_all_jobs()


def reset_mock_api(server: "SimpleTestServer") -> None:
    """Clear queued expectations and unexpected request log from the mock server.

    Args:
        server: The SimpleTestServer instance to reset.
    """
    server._expectations.clear()
    server._unexpected.clear()


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
    hassette.mark_ready("reset for test")
    if original_children is not None:
        hassette.children[:] = original_children

    _reset_resource_flags(hassette)
