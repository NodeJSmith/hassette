"""Tests for Resource.start_children_and_wait().

Verifies:
- Happy path: all children start and become ready
- Empty children: returns immediately without error
- Timeout: raises TimeoutError with diagnostic listing
- Shutdown during wait: raises TimeoutError
"""

import pytest

from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.resources.operations import start_children_and_wait
from hassette.test_utils import make_mock_hassette


class Parent(Resource):
    """Minimal parent resource for testing."""

    async def on_initialize(self) -> None:
        pass


class ReadyOnInit(Resource):
    """Child that becomes ready immediately on initialize."""

    async def on_initialize(self) -> None:
        mark_ready(self, "initialized")


class NeverReady(Resource):
    """Child that never signals readiness."""

    async def on_initialize(self) -> None:
        pass


async def test_all_children_become_ready():
    hassette = make_mock_hassette(sealed=False)
    parent = Parent(hassette)
    parent.add_child(ReadyOnInit)
    parent.add_child(ReadyOnInit)

    await start_children_and_wait(parent, timeout=2.0)

    assert all(c.is_ready() for c in parent.children)


async def test_empty_children_is_noop():
    hassette = make_mock_hassette(sealed=False)
    parent = Parent(hassette)

    await start_children_and_wait(parent, timeout=1.0)

    assert parent.children == []


async def test_timeout_raises_with_diagnostics():
    hassette = make_mock_hassette(sealed=False)
    parent = Parent(hassette)
    parent.add_child(ReadyOnInit)
    parent.add_child(NeverReady)

    with pytest.raises(TimeoutError, match=r"timed out after 0\.1s.*NeverReady"):
        await start_children_and_wait(parent, timeout=0.1)


async def test_shutdown_during_wait_raises():
    hassette = make_mock_hassette(sealed=False)
    parent = Parent(hassette)
    parent.add_child(NeverReady)

    hassette.shutdown_event.set()

    with pytest.raises(TimeoutError, match="shutdown during wait"):
        await start_children_and_wait(parent, timeout=1.0)
