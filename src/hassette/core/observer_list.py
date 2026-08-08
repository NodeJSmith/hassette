"""A small list of async observer callbacks with add/remove/notify.

Extracted from :mod:`hassette.core.websocket_service`, which had four near-identical
registration methods (add/remove for a connected-observer list and a disconnected-observer
list) and two near-identical notify methods, differing only in which list they touched and
whether the callback took a ``generation`` argument.
"""

import typing
from collections.abc import Callable
from logging import Logger
from typing import Generic, TypeVar

T = TypeVar("T", bound=Callable[..., typing.Awaitable[None]])


class ObserverList(Generic[T]):
    """An ordered, deduplicated list of async callbacks, notified in registration order.

    A failing observer is logged and does not prevent the remaining observers from running —
    matches the original ``WebsocketService`` behavior, where one broken observer (e.g.
    ``StateProxy``'s initial sync) must not block the others.
    """

    def __init__(self, logger: Logger, label: str) -> None:
        self._observers: list[T] = []
        self._logger = logger
        self._label = label

    def add(self, observer: T) -> None:
        if observer not in self._observers:
            self._observers.append(observer)

    def remove(self, observer: T) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    async def notify(self, *args: typing.Any) -> None:
        for observer in tuple(self._observers):
            try:
                await observer(*args)
            except Exception:
                self._logger.exception("%s observer failed", self._label)
