"""Shared helpers for lifecycle propagation tests."""

import asyncio
from typing import TypeVar
from unittest.mock import AsyncMock

from hassette.resources.base import Resource
from hassette.resources.service import Service
from hassette.resources.shutdown_outcome import ShutdownOutcome, merge_outcomes
from tests.support.mock_hassette import make_mock_hassette
from tests.unit.resources.conftest import ConcreteResource, wait_for_running

ResourceT = TypeVar("ResourceT", bound=Resource)
ParentT = TypeVar("ParentT", bound=Resource)

__all__ = [
    "ConcreteResource",
    "ErrorChild",
    "HangingChild",
    "OrderTrackingChild",
    "PendingTaskChild",
    "ShutdownCounter",
    "SimpleParent",
    "SimpleService",
    "make_initialized_shutdown_counter",
    "make_parent_with_child",
    "make_running_simple_service",
]


class ShutdownCounter(Resource):
    """Resource that counts on_shutdown calls."""

    shutdown_count: int = 0

    async def on_shutdown(self) -> None:
        self.shutdown_count += 1


class HangingChild(Resource):
    """Resource whose ``on_shutdown()`` never completes on its own — a plain, uncaught ``Event().wait()``.

    The hook is cut off at its own bound (``shutdown_timeout_seconds``, clamped to any shutdown deadline)
    and recorded as ``TIMED_OUT``, so it is useful anywhere a test wants a hook-timeout
    outcome. For a hook that swallows its cancellation and holds the shutdown until the owner
    force-terminates it, see ``TrulyResistantChild`` in ``test_shutdown_coordinator.py``.
    """

    async def on_shutdown(self) -> None:
        await asyncio.Event().wait()


# Shared list to record shutdown order across multiple children
shutdown_order: list[str] = []


class OrderTrackingChild(Resource):
    """Resource that appends its unique_name to a shared list on shutdown."""

    async def on_shutdown(self) -> None:
        shutdown_order.append(self.unique_name)


class PendingTaskChild(Resource):
    """Resource whose shutdown outcome names a task still pending, so its outcome is restart-unsafe.

    Stands in for a child whose own work outlived its shutdown without making a test hold a task that
    ignores cancellation.
    """

    async def _shutdown_body(self) -> ShutdownOutcome:
        outcome = await super()._shutdown_body()
        return merge_outcomes(outcome, ShutdownOutcome(still_running=("stuck-task",)))


class ErrorChild(Resource):
    """Resource that raises during on_shutdown."""

    async def on_shutdown(self) -> None:
        shutdown_order.append(self.unique_name)
        raise RuntimeError(f"{self.unique_name} exploded")


class SimpleParent(Resource):
    """Parent resource with no custom shutdown logic."""

    pass


class SimpleService(Service):
    """Service that runs indefinitely until cancelled."""

    required = False

    async def serve(self) -> None:
        await asyncio.Event().wait()  # block forever


def make_parent_with_child(
    order_list: list, child_cls: type[ResourceT], hassette: AsyncMock | None = None
) -> tuple[SimpleParent, ResourceT]:
    """Clear `order_list`, build a `SimpleParent`, and attach one `child_cls` child.

    Callers needing more than one child add the rest with `parent.add_child(...)` after.
    The mock hassette is reachable as `parent.hassette` if needed.
    """
    order_list.clear()
    hassette = hassette or make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)
    child = parent.add_child(child_cls)
    return parent, child


async def shut_down_parent_with_child(
    parent_cls: type[ParentT], child_cls: type[ResourceT]
) -> tuple[ParentT, ResourceT, ShutdownOutcome]:
    """Build `parent_cls` with one `child_cls` child, initialize both, shut the parent down, and return
    the parent, the child and the parent's outcome.
    """
    parent = parent_cls(make_mock_hassette(sealed=False))
    child = parent.add_child(child_cls)
    await parent.initialize()
    await child.initialize()
    outcome = await parent.shutdown()
    return parent, child, outcome


async def make_running_simple_service(hassette: AsyncMock | None = None) -> SimpleService:
    """Build a `SimpleService`, initialize it, and wait for it to reach RUNNING."""
    hassette = hassette or make_mock_hassette(sealed=False)
    svc = SimpleService(hassette)
    await svc.initialize()
    await wait_for_running(svc)
    return svc


async def make_initialized_shutdown_counter(hassette: AsyncMock | None = None) -> ShutdownCounter:
    """Build a `ShutdownCounter` and initialize it."""
    hassette = hassette or make_mock_hassette(sealed=False)
    resource = ShutdownCounter(hassette)
    await resource.initialize()
    return resource
