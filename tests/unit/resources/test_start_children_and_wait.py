"""Tests for Resource.start_children_and_wait().

Verifies:
- Happy path: all children start and become ready
- Empty children: returns immediately without error
- Timeout: raises TimeoutError with diagnostic listing
- Shutdown during wait: raises TimeoutError
- Failed child initialization: raises at once, chained from the child's exception
"""

import asyncio

import pytest

from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.resources.operations import start_children_and_wait
from tests.support.mock_hassette import make_mock_hassette


class Parent(Resource):
    """Minimal parent resource for testing."""

    async def on_initialize(self) -> None:
        pass


class ReadyOnInit(Resource):
    """Child that becomes ready immediately on initialize."""

    async def on_initialize(self) -> None:
        mark_ready(self, "initialized")


class FailsOnInit(Resource):
    """Child whose initialization raises after it already marked itself ready."""

    async def on_initialize(self) -> None:
        mark_ready(self, "initialized")
        raise ValueError("bad config")


class NeverReady(Resource):
    """Child that never signals readiness."""

    async def on_initialize(self) -> None:
        pass


@pytest.fixture
def parent() -> Parent:
    return Parent(make_mock_hassette(sealed=False))


async def test_all_children_become_ready(parent: Parent):
    parent.add_child(ReadyOnInit)
    parent.add_child(ReadyOnInit)

    await start_children_and_wait(parent, timeout=2.0)

    assert all(c.is_ready() for c in parent.children)


async def test_empty_children_is_noop(parent: Parent):

    await start_children_and_wait(parent, timeout=1.0)

    assert parent.children == []


async def test_timeout_raises_with_diagnostics(parent: Parent):
    parent.add_child(ReadyOnInit)
    parent.add_child(NeverReady)

    with pytest.raises(TimeoutError, match=r"timed out after 0\.1s.*NeverReady"):
        await start_children_and_wait(parent, timeout=0.1)


async def test_shutdown_during_wait_raises(parent: Parent):
    parent.add_child(NeverReady)

    parent.hassette.shutdown_event.set()

    with pytest.raises(TimeoutError, match="shutdown during wait"):
        await start_children_and_wait(parent, timeout=1.0)


async def test_failed_child_raises_without_waiting_for_timeout(parent: Parent):
    parent.add_child(ReadyOnInit)
    parent.add_child(FailsOnInit)

    with pytest.raises(RuntimeError, match=r"failed to initialize: FailsOnInit \(ValueError: bad config\)") as exc_info:
        await asyncio.wait_for(start_children_and_wait(parent, timeout=60.0), timeout=5.0)

    assert isinstance(exc_info.value.__cause__, ValueError)
