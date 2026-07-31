"""StateProxy test-double helpers."""

from typing import Any
from unittest.mock import AsyncMock

from hassette.core.state_proxy import StateCacheFreshness, StateSynchronizationStatus


def configure_state_proxy_mock(
    state_proxy: Any,
    *,
    states: dict[str, Any] | None = None,
    is_ready: bool = True,
    has_state_capability: bool = True,
    cache_freshness: StateCacheFreshness | None = None,
) -> None:
    """Stamp a consistent StateProxy capability profile onto a mock."""
    state_proxy.states = states if states is not None else {}
    state_proxy.has_cache_entries = bool(state_proxy.states)
    state_proxy.is_ready.return_value = is_ready
    state_proxy.has_initial_state_capability.return_value = has_state_capability
    state_proxy.wait_initial_state_capability = AsyncMock(return_value=has_state_capability)
    state_proxy.synchronization_status = StateSynchronizationStatus.IDLE
    state_proxy.maintained_generation = 1 if has_state_capability else None
    if cache_freshness is not None:
        state_proxy.cache_freshness = cache_freshness
    elif has_state_capability:
        state_proxy.cache_freshness = StateCacheFreshness.FRESH
    else:
        state_proxy.cache_freshness = StateCacheFreshness.UNAVAILABLE
