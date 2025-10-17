# pyright: reportInvalidTypeArguments=none, reportArgumentType=none

import asyncio
from types import SimpleNamespace

from hassette.events.base import Event


async def test_once_listener_removed(hassette_with_bus) -> None:
    hassette = hassette_with_bus

    payloads: list[int] = []
    first_fired = asyncio.Event()

    async def handler(event: Event[SimpleNamespace]) -> None:
        payloads.append(event.payload.value)
        first_fired.set()

    hassette._bus.on(topic="custom.once", handler=handler, once=True)

    await hassette.send_event("custom.once", Event(topic="custom.once", payload=SimpleNamespace(value=1)))

    await asyncio.wait_for(first_fired.wait(), timeout=1)
    await asyncio.sleep(0.05)

    await hassette.send_event("custom.once", Event(topic="custom.once", payload=SimpleNamespace(value=2)))

    await asyncio.sleep(0.1)

    assert payloads == [1], f"Expected handler to fire once with payload 1, got {payloads}"


async def test_bus_background_tasks_cleanup(hassette_with_bus) -> None:
    hassette = hassette_with_bus

    fired = asyncio.Event()

    async def handler(event: Event[SimpleNamespace]) -> None:  # noqa
        fired.set()

    hassette._bus.on(topic="custom.cleanup", handler=handler, once=True)

    await hassette.send_event("custom.cleanup", Event(topic="custom.cleanup", payload=SimpleNamespace(value=9)))

    await asyncio.wait_for(fired.wait(), timeout=1)
    await asyncio.sleep(0.1)

    assert len(hassette._bus.task_bucket) == 0, (
        f"Expected no leftover bus tasks, found {len(hassette._bus.task_bucket)}"
    )


async def test_bus_uses_args_kwargs(hassette_with_bus) -> None:
    hassette = hassette_with_bus

    received: list[str] = []
    fired = asyncio.Event()

    def handler(event: Event[SimpleNamespace], prefix: str, suffix: str) -> None:
        received.append(f"{prefix}{event.payload.value}{suffix}")
        fired.set()

    hassette._bus.on(topic="custom.args", handler=handler, args=("Value: ",), kwargs={"suffix": "!"})

    await hassette.send_event("custom.args", Event(topic="custom.args", payload=SimpleNamespace(value="Test")))

    await asyncio.wait_for(fired.wait(), timeout=1)

    assert received == ["Value: Test!"], f"Expected handler to receive formatted value, got {received}"
