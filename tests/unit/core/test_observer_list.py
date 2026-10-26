"""Unit tests for ObserverList's failure isolation."""

import logging
from typing import TYPE_CHECKING

from hassette.core.observer_list import ObserverList

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


async def test_failing_observer_does_not_stop_later_observers() -> None:
    """An observer that raises is skipped; observers registered after it still run, in order."""
    calls: list[str] = []

    async def first(value: int) -> None:
        calls.append(f"first:{value}")

    async def broken(value: int) -> None:  # noqa: ARG001
        calls.append("broken")
        raise RuntimeError("observer exploded")

    async def last(value: int) -> None:
        calls.append(f"last:{value}")

    observers: ObserverList[Callable[[int], Awaitable[None]]] = ObserverList(
        logging.getLogger("test_observer_list"), "test"
    )
    for observer in (first, broken, last):
        observers.add(observer)

    await observers.notify(7)

    assert calls == ["first:7", "broken", "last:7"]
