"""Shared helpers for StateProxy integration tests (test_state_proxy.py)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast
from unittest.mock import Mock

from hassette.core.state_proxy import StateProxy
from hassette.events import HassStateDict, RawStateChangeEvent
from hassette.events.metadata import stamp_websocket_generation
from hassette.testing import make_light_state_dict


def api_mock(proxy: StateProxy) -> Mock:
    """Return the proxy's Home Assistant API as the ``Mock`` that ``build_state_proxy`` installs."""
    return cast("Mock", proxy.hassette.api)


def ws_mock(proxy: StateProxy) -> Mock:
    """Return the proxy's websocket service as the ``Mock`` that ``build_state_proxy`` installs."""
    return cast("Mock", proxy.hassette.websocket_service)


def cached_light_state(entity_id: str, state: str, **kwargs: Any) -> HassStateDict:
    """Build a light state dict typed as a ``StateProxy.states`` cache entry."""
    return cast("HassStateDict", make_light_state_dict(entity_id, state, **kwargs))


def with_websocket_generation(event: RawStateChangeEvent, generation: int) -> RawStateChangeEvent:
    stamp_websocket_generation(event, generation)
    return event


def gated_get_states_raw_factory(
    result: list[dict[str, object]] | None = None,
    error: Exception | None = None,
) -> tuple[asyncio.Event, asyncio.Event, Callable[[], Awaitable[list[dict[str, object]]]]]:
    """Build a gated ``api.get_states_raw`` side effect for ``AsyncMock(side_effect=...)``.

    Collapses the repeated snapshot_entered/release_snapshot gate scaffold duplicated across
    test_state_proxy.py's reconnect/retry tests (issue #1493) into one helper.

    Returns ``(entered, release, side_effect)``: ``entered`` is set the moment the side effect
    starts running — await it to know the snapshot call has begun. The side effect then blocks
    on ``release`` (call ``.set()`` to let it proceed) before returning ``result`` (default
    ``[]``) or raising ``error`` if given. If ``release`` is never set, the call blocks
    forever — useful for tests that assert on cancellation rather than completion.
    """
    entered = asyncio.Event()
    release = asyncio.Event()

    async def side_effect() -> list[dict[str, object]]:
        entered.set()
        await release.wait()
        if error is not None:
            raise error
        return result if result is not None else []

    return entered, release, side_effect
