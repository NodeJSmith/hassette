"""Reset utilities for test fixtures.

Provides functions to reset Resource state between tests, enabling module-scoped
fixtures without test pollution.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hassette.core.state_proxy import StateProxy


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
