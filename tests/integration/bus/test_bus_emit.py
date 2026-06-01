"""Integration tests for Bus.emit and D.EventData[T]."""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hassette import D
from hassette.events.base import Event, HassettePayload

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness


@dataclass(frozen=True)
class SomeData:
    value: str
    count: int = 0


async def test_bus_emit_delivers_to_subscriber(hassette_with_bus: "HassetteHarness") -> None:
    """bus.emit delivers the event to a handler subscribed to the same topic."""
    bus = hassette_with_bus.bus
    received: list[Event] = []
    done = asyncio.Event()

    async def handler(event: Event) -> None:
        received.append(event)
        hassette_with_bus.task_bucket.post_to_loop(done.set)

    await bus.on(topic="test.emit_topic", handler=handler, name="test_emit_subscriber")

    await bus.emit("test.emit_topic", SomeData(value="hello", count=42))

    await asyncio.wait_for(done.wait(), timeout=2.0)

    assert len(received) == 1
    event = received[0]
    assert event.topic == "test.emit_topic"
    assert isinstance(event.payload, HassettePayload)
    assert event.payload.data == SomeData(value="hello", count=42)


async def test_bus_emit_event_data_di_accessor(hassette_with_bus: "HassetteHarness") -> None:
    """A handler annotated with D.EventData[SomeData] receives the pre-extracted typed data."""
    bus = hassette_with_bus.bus
    received_data: list[SomeData] = []
    done = asyncio.Event()

    async def handler(data: D.EventData[SomeData]) -> None:
        received_data.append(data)
        hassette_with_bus.task_bucket.post_to_loop(done.set)

    await bus.on(topic="test.di_topic", handler=handler, name="test_di_subscriber")

    await bus.emit("test.di_topic", SomeData(value="typed", count=7))

    await asyncio.wait_for(done.wait(), timeout=2.0)

    assert len(received_data) == 1
    assert received_data[0] == SomeData(value="typed", count=7)


async def test_bus_emit_self_delivery(hassette_with_bus: "HassetteHarness") -> None:
    """An app that emits and subscribes to the same topic receives its own event (FR#7/AC#8)."""
    bus = hassette_with_bus.bus
    received: list[SomeData] = []
    done = asyncio.Event()

    async def handler(data: D.EventData[SomeData]) -> None:
        received.append(data)
        hassette_with_bus.task_bucket.post_to_loop(done.set)

    await bus.on(topic="test.self_delivery", handler=handler, name="test_self_delivery_sub")

    await bus.emit("test.self_delivery", SomeData(value="self", count=1))

    await asyncio.wait_for(done.wait(), timeout=2.0)

    assert len(received) == 1
    assert received[0].value == "self"


async def test_bus_sync_emit_delivers_event(hassette_with_bus: "HassetteHarness") -> None:
    """bus.sync.emit delivers the event from a synchronous context (FR#6/AC#4)."""
    bus = hassette_with_bus.bus
    received: list[SomeData] = []
    done = asyncio.Event()

    async def handler(data: D.EventData[SomeData]) -> None:
        received.append(data)
        hassette_with_bus.task_bucket.post_to_loop(done.set)

    await bus.on(topic="test.sync_emit_topic", handler=handler, name="test_sync_emit_sub")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: bus.sync.emit("test.sync_emit_topic", SomeData(value="sync", count=99)),
    )

    await asyncio.wait_for(done.wait(), timeout=2.0)

    assert len(received) == 1
    assert received[0] == SomeData(value="sync", count=99)


async def test_bus_emit_no_subscribers(hassette_with_bus: "HassetteHarness") -> None:
    """emit with no subscribers completes without error."""
    bus = hassette_with_bus.bus
    await bus.emit("test.no_subscribers", SomeData(value="dropped", count=0))


def test_app_has_no_send_event() -> None:
    """App.send_event and AppSync.send_event_sync no longer exist (FR#5/AC#3)."""
    from hassette.app.app import App, AppSync

    assert not hasattr(App, "send_event"), "App.send_event should not exist after clean break removal"
    assert not hasattr(AppSync, "send_event_sync"), "AppSync.send_event_sync should not exist after clean break removal"
