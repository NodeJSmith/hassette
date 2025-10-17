# pyright: reportInvalidTypeArguments=none, reportArgumentType=none

import asyncio
from types import SimpleNamespace

from hassette.events.base import Event


async def test_once_listener_removed(hassette_with_bus) -> None:
    """Listeners registered with once=True are removed after the first invocation."""
    hassette = hassette_with_bus

    received_payloads: list[int] = []
    first_invocation = asyncio.Event()

    async def handler(event: Event[SimpleNamespace]) -> None:
        received_payloads.append(event.payload.value)
        first_invocation.set()

    hassette._bus.on(topic="custom.once", handler=handler, once=True)

    await hassette.send_event("custom.once", Event(topic="custom.once", payload=SimpleNamespace(value=1)))

    await asyncio.wait_for(first_invocation.wait(), timeout=1)
    await asyncio.sleep(0.05)

    await hassette.send_event("custom.once", Event(topic="custom.once", payload=SimpleNamespace(value=2)))

    await asyncio.sleep(0.1)

    assert received_payloads == [1], f"Expected handler to fire once with payload 1, got {received_payloads}"


async def test_bus_background_tasks_cleanup(hassette_with_bus) -> None:
    """Bus cleans up background tasks after a once handler completes."""
    hassette = hassette_with_bus

    event_received = asyncio.Event()

    async def handler(event: Event[SimpleNamespace]) -> None:  # noqa
        event_received.set()

    hassette._bus.on(topic="custom.cleanup", handler=handler, once=True)

    await hassette.send_event("custom.cleanup", Event(topic="custom.cleanup", payload=SimpleNamespace(value=9)))

    await asyncio.wait_for(event_received.wait(), timeout=1)
    await asyncio.sleep(0.1)

    assert len(hassette._bus.task_bucket) == 0, (
        f"Expected no leftover bus tasks, found {len(hassette._bus.task_bucket)}"
    )


async def test_bus_uses_args_kwargs(hassette_with_bus) -> None:
    """Handlers receive configured args and kwargs when invoked."""
    hassette = hassette_with_bus

    formatted_messages: list[str] = []
    event_processed = asyncio.Event()

    def handler(event: Event[SimpleNamespace], prefix: str, suffix: str) -> None:
        formatted_messages.append(f"{prefix}{event.payload.value}{suffix}")
        event_processed.set()

    hassette._bus.on(topic="custom.args", handler=handler, args=("Value: ",), kwargs={"suffix": "!"})

    await hassette.send_event("custom.args", Event(topic="custom.args", payload=SimpleNamespace(value="Test")))

    await asyncio.wait_for(event_processed.wait(), timeout=1)

    assert formatted_messages == ["Value: Test!"], (
        f"Expected handler to receive formatted value, got {formatted_messages}"
    )
