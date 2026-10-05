"""Unit tests for wait_for_ready() in hassette.utils.service_utils.

Covers concurrent waiting on independent dependencies: every resource's ``wait_ready``
is awaited at once, readiness order does not matter, and one dependency timing out fails
the whole wait even when the others become ready.

Each test runs with and without a ``shutdown_event`` because ``wait_for_ready`` takes a different
code path for each: a plain ``gather`` without one, a ``gather`` raced against the event with one.
"""

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

from hassette.utils import wait_for_ready

if TYPE_CHECKING:
    from hassette.resources.base import Resource

WAIT_TIMEOUT = 1.0
"""Deadline for waits expected to succeed; far above the time event-driven readiness takes."""

SHORT_TIMEOUT = 0.05
"""Deadline for the wait that is expected to time out."""


class StubResource:
    """Duck-typed stand-in for Resource that exposes only the readiness surface wait_for_ready uses."""

    def __init__(self) -> None:
        self.ready_event = asyncio.Event()
        self.waiting = asyncio.Event()
        self.finished = asyncio.Event()

    async def wait_ready(self, timeout: float | None = None) -> None:
        self.waiting.set()
        if timeout is None:
            await self.ready_event.wait()
        else:
            await asyncio.wait_for(self.ready_event.wait(), timeout)
        self.finished.set()


def as_resources(*stubs: StubResource) -> "list[Resource]":
    return cast("list[Resource]", list(stubs))


@pytest.mark.parametrize("with_shutdown_event", [False, True])
async def test_independent_deps_are_awaited_concurrently(with_shutdown_event: bool) -> None:
    """Every dependency's wait_ready starts before any of them is ready."""
    dep_a, dep_b = StubResource(), StubResource()
    shutdown = asyncio.Event() if with_shutdown_event else None

    task = asyncio.create_task(
        wait_for_ready(as_resources(dep_a, dep_b), timeout=WAIT_TIMEOUT, shutdown_event=shutdown)
    )
    await asyncio.wait_for(asyncio.gather(dep_a.waiting.wait(), dep_b.waiting.wait()), timeout=WAIT_TIMEOUT)

    assert not task.done(), "wait_for_ready must still be waiting while neither dep is ready"

    dep_a.ready_event.set()
    dep_b.ready_event.set()
    assert await task is True


@pytest.mark.parametrize("with_shutdown_event", [False, True])
async def test_deps_ready_at_different_times_in_reverse_order(with_shutdown_event: bool) -> None:
    """The second dep's wait completes while the first is still pending; the overall wait ends once both are ready."""
    dep_a, dep_b = StubResource(), StubResource()
    shutdown = asyncio.Event() if with_shutdown_event else None

    task = asyncio.create_task(
        wait_for_ready(as_resources(dep_a, dep_b), timeout=WAIT_TIMEOUT, shutdown_event=shutdown)
    )

    dep_b.ready_event.set()
    await asyncio.wait_for(dep_b.finished.wait(), timeout=WAIT_TIMEOUT)
    assert not dep_a.finished.is_set()
    assert not task.done(), "wait_for_ready must not finish while dep_a is still not ready"

    dep_a.ready_event.set()
    assert await asyncio.wait_for(task, timeout=WAIT_TIMEOUT) is True


@pytest.mark.parametrize("with_shutdown_event", [False, True])
async def test_one_dep_times_out_while_other_succeeds(with_shutdown_event: bool) -> None:
    """A dep that never becomes ready fails the wait even though the other dep is ready."""
    ready_dep, stuck_dep = StubResource(), StubResource()
    ready_dep.ready_event.set()
    shutdown = asyncio.Event() if with_shutdown_event else None

    result = await wait_for_ready(as_resources(ready_dep, stuck_dep), timeout=SHORT_TIMEOUT, shutdown_event=shutdown)

    assert result is False
    assert ready_dep.ready_event.is_set()
    assert not stuck_dep.ready_event.is_set()
