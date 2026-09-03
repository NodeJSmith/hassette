"""Shared helpers for lifecycle propagation tests."""

import asyncio
from unittest.mock import AsyncMock

from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from tests.support.factories import make_mock_hassette
from tests.unit.resources.conftest import ConcreteResource, wait_for_running

__all__ = [
    "ConcreteResource",
    "ErrorChild",
    "HangingChild",
    "OrderTrackingChild",
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
    """Resource whose ``on_shutdown()`` never completes on its own — a plain, uncaught
    ``Event().wait()``.

    Since ``bound_to_shutdown_budget=True`` was added to the ``run_hooks()`` calls in
    ``_shutdown_body()`` (PR #1723), this no longer hangs *indefinitely*: the hook is caught by
    the shared shutdown budget's own inner ``asyncio.timeout()`` and resolves with a
    ``TimeoutError`` (recorded as ``SHUTDOWN_HOOK_FAILED``) within roughly
    ``resource_shutdown_timeout_seconds`` — it still never *gracefully* completes, so it remains
    useful anywhere a test wants shutdown/child-teardown failure evidence. For a fixture that
    genuinely resists cancellation and would still hang the whole shutdown body past the
    coordinator's own outer wait (catches ``CancelledError`` and re-blocks), see
    ``TrulyResistantChild`` in ``test_shutdown.py``.
    """

    async def on_shutdown(self) -> None:
        await asyncio.Event().wait()


# Shared list to record shutdown order across multiple children
shutdown_order: list[str] = []


class OrderTrackingChild(Resource):
    """Resource that appends its unique_name to a shared list on shutdown."""

    async def on_shutdown(self) -> None:
        shutdown_order.append(self.unique_name)


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

    restart_spec = RestartSpec()

    async def serve(self) -> None:
        await asyncio.Event().wait()  # block forever


def make_parent_with_child(
    order_list: list, child_cls: type[Resource], hassette: AsyncMock | None = None
) -> tuple[SimpleParent, Resource]:
    """Clear `order_list`, build a `SimpleParent`, and attach one `child_cls` child.

    Callers needing more than one child add the rest with `parent.add_child(...)` after.
    The mock hassette is reachable as `parent.hassette` if needed.
    """
    order_list.clear()
    hassette = hassette or make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)
    child = parent.add_child(child_cls)
    return parent, child


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
