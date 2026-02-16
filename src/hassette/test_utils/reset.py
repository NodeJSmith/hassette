"""Reset utilities for test fixtures.

Provides functions to reset Resource state between tests, enabling module-scoped
fixtures without test pollution.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hassette.bus.bus import Bus
    from hassette.core.state_proxy import StateProxy
    from hassette.scheduler.scheduler import Scheduler
    from hassette.test_utils.test_server import SimpleTestServer


async def reset_state_proxy(proxy: "StateProxy") -> None:
    """Reset StateProxy to a clean state for testing.

    Clears the internal states cache and removes any test-added bus listeners.
    The proxy remains ready and its initialization listeners stay intact.
    This allows module-scoped fixtures to be reused across tests without
    state pollution.

    Args:
        proxy: The StateProxy instance to reset

    Example:
        >>> async def cleanup_state_proxy(proxy: StateProxy):
        ...     await reset_state_proxy(proxy)
    """
    # Clear the states cache
    async with proxy.lock:
        proxy.states.clear()

    await proxy.on_shutdown()
    await proxy.on_initialize()


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
