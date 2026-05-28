"""Shared helpers for lifecycle propagation tests."""

import asyncio

from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from tests.unit.resources.conftest import ConcreteResource

__all__ = [
    "ConcreteResource",
    "ErrorChild",
    "HangingChild",
    "OrderTrackingChild",
    "ShutdownCounter",
    "SimpleParent",
    "SimpleService",
]


class ShutdownCounter(Resource):
    """Resource that counts on_shutdown calls."""

    shutdown_count: int = 0

    async def on_shutdown(self) -> None:
        self.shutdown_count += 1


class HangingChild(Resource):
    """Resource whose shutdown hangs indefinitely."""

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
