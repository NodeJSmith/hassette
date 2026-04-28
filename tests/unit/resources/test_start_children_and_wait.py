"""Tests for Resource.start_children_and_wait().

Verifies:
- Happy path: all children start and become ready
- Empty children: returns immediately without error
- Timeout: raises TimeoutError with diagnostic listing
- Shutdown during wait: raises TimeoutError
"""

import pytest

from hassette.resources.base import Resource

from .conftest import _make_hassette_stub


class _Parent(Resource):
    """Minimal parent resource for testing."""

    async def on_initialize(self) -> None:
        pass


class _ReadyOnInit(Resource):
    """Child that becomes ready immediately on initialize."""

    async def on_initialize(self) -> None:
        self.mark_ready("initialized")


class _NeverReady(Resource):
    """Child that never signals readiness."""

    async def on_initialize(self) -> None:
        pass


@pytest.mark.asyncio
async def test_all_children_become_ready():
    hassette = _make_hassette_stub()
    parent = _Parent(hassette)
    parent.add_child(_ReadyOnInit)
    parent.add_child(_ReadyOnInit)

    await parent.start_children_and_wait(timeout=2.0)

    assert all(c.is_ready() for c in parent.children)


@pytest.mark.asyncio
async def test_empty_children_is_noop():
    hassette = _make_hassette_stub()
    parent = _Parent(hassette)

    await parent.start_children_and_wait(timeout=1.0)

    assert parent.children == []


@pytest.mark.asyncio
async def test_timeout_raises_with_diagnostics():
    hassette = _make_hassette_stub()
    parent = _Parent(hassette)
    parent.add_child(_ReadyOnInit)
    parent.add_child(_NeverReady)

    with pytest.raises(TimeoutError, match=r"timed out after 0\.1s.*_NeverReady"):
        await parent.start_children_and_wait(timeout=0.1)


@pytest.mark.asyncio
async def test_shutdown_during_wait_raises():
    hassette = _make_hassette_stub()
    parent = _Parent(hassette)
    parent.add_child(_NeverReady)

    hassette.shutdown_event.set()

    with pytest.raises(TimeoutError, match="shutdown during wait"):
        await parent.start_children_and_wait(timeout=1.0)
