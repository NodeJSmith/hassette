from collections import defaultdict
from collections.abc import Callable
from fnmatch import fnmatch

from fair_async_rlock import FairAsyncRLock

from .listeners import Listener

GLOB_CHARS = "*?["


class Router:
    exact: dict[str, list[Listener]]
    globs: dict[str, list[Listener]]
    owners: dict[str, list[Listener]]

    def __init__(self) -> None:
        # self.lock = asyncio.Lock()
        self.lock = FairAsyncRLock()
        self.exact = defaultdict(list)
        self.globs = defaultdict(list)  # keys contain glob chars
        self.owners = defaultdict(list)

    async def add_route(self, topic: str, listener: Listener) -> None:
        """Add a listener to the appropriate route based on whether it contains glob characters.

        Args:
            topic (str): The topic to add the listener to.
            listener (Listener): The listener to add.

        """
        async with self.lock:
            if any(ch in topic for ch in GLOB_CHARS):
                self.globs[topic].append(listener)
            else:
                self.exact[topic].append(listener)

            self.owners[listener.owner].append(listener)

    async def remove_route(self, topic: str, predicate: Callable[[Listener], bool]) -> None:
        """Remove a listener from the appropriate route based on whether it contains glob characters.

        Args:
            topic (str): The topic to remove the listener from.
            predicate (callable): A function that returns True for listeners to be removed.
        """

        bucket = self.globs if any(ch in topic for ch in GLOB_CHARS) else self.exact

        async with self.lock:
            if topic in bucket:
                bucket[topic] = list(filter(lambda x: not predicate(x), bucket[topic]))
                if not bucket[topic]:
                    bucket.pop(topic, None)

            # Also remove from owners
            for owner, listeners in list(self.owners.items()):
                self.owners[owner] = list(filter(lambda x: not predicate(x), listeners))
                if not self.owners[owner]:
                    self.owners.pop(owner, None)

    async def remove_listener(self, listener: Listener) -> None:
        """Remove a specific listener from the router.

        Args:
            listener (Listener): The listener to remove.
        """

        def pred(x: Listener) -> bool:
            return x.listener_id == listener.listener_id

        await self.remove_route(listener.topic, pred)

    async def remove_listener_by_id(self, topic: str, listener_id: int) -> None:
        """Remove a listener by its ID.

        Args:
            topic (str): The topic the listener is associated with.
            listener_id (int): The ID of the listener to remove.
        """

        def pred(x: Listener) -> bool:
            return x.listener_id == listener_id

        await self.remove_route(topic, pred)

    async def get_matching_listeners(self, topic: str) -> list[Listener]:
        """Get all listeners that match the given topic.

        Args:
            topic (str): The topic to match against.

        Returns:
            list[Listener]: A list of listeners that match the topic.
        """
        async with self.lock:
            out: list[Listener] = []
            out.extend(self.exact.get(topic, ()))

            for k, listener in self.globs.items():
                if fnmatch(topic, k):
                    out.extend(listener)

            # de-dup preserving order
            seen, unique = set(), []
            for listener in out:
                if id(listener) not in seen:
                    seen.add(id(listener))
                    unique.append(listener)
            return unique

    async def clear_owner(self, owner: str) -> None:
        """Remove all listeners associated with the given owner.

        Args:
            owner (str): The owner whose listeners should be removed.
        """

        if owner not in self.owners:
            return

        async with self.lock:
            for listener in self.owners[owner]:
                await self.remove_route(listener.topic, lambda x: x.owner == owner)

            self.owners.pop(owner, None)
