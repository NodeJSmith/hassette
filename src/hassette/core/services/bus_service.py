import asyncio
import itertools
import typing
from collections import defaultdict
from collections.abc import Callable
from fnmatch import fnmatch
from typing import Any

from anyio.streams.memory import MemoryObjectReceiveStream
from fair_async_rlock import FairAsyncRLock

from hassette.core.resources.base import Service

if typing.TYPE_CHECKING:
    from hassette import Hassette, Listener
    from hassette.events import Event


GLOB_CHARS = "*?["


class _BusService(Service):  # pyright: ignore[reportUnusedClass]
    """EventBus service that handles event dispatching and listener management."""

    def __init__(self, hassette: "Hassette", stream: MemoryObjectReceiveStream["tuple[str, Event[Any]]"]):
        super().__init__(hassette)
        self.set_logger_to_level(self.hassette.config.bus_service_log_level)

        self.stream = stream

        self.listener_seq = itertools.count(1)
        self.router = Router()

    def _log_task_result(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return

        exc = task.exception()
        if exc:
            self.logger.error("Bus background task failed", exc_info=exc)

    def add_listener(self, listener: "Listener") -> None:
        """Add a listener to the bus."""
        self.task_bucket.spawn(self.router.add_route(listener.topic, listener), name="bus:add_listener")

    def remove_listener(self, listener: "Listener") -> None:
        """Remove a listener from the bus."""
        self.remove_listener_by_id(listener.topic, listener.listener_id)

    def remove_listener_by_id(self, topic: str, listener_id: int) -> None:
        """Remove a listener by its ID."""
        self.task_bucket.spawn(self.router.remove_listener_by_id(topic, listener_id), name="bus:remove_listener")

    def remove_listeners_by_owner(self, owner: str) -> None:
        """Remove all listeners owned by a specific owner."""
        self.task_bucket.spawn(self.router.clear_owner(owner), name="bus:remove_listeners_by_owner")

    async def dispatch(self, topic: str, event: "Event[Any]") -> None:
        """Dispatch an event to all matching listeners for the given topic."""
        try:
            if (
                event.payload.event_type == "call_service"
                and event.payload.data.domain == "system_log"
                and event.payload.data.service_data.get("level") == "debug"
            ):
                return
        except Exception:
            pass

        targets = await self.router.get_matching_listeners(topic)

        self.logger.debug("Event: %r", event)

        if not targets:
            return

        self.logger.debug("Dispatching %s to %d listeners", topic, len(targets))
        self.logger.debug("Listeners for %s: %r", topic, targets)

        for listener in targets:
            self.task_bucket.spawn(self._dispatch(topic, event, listener), name="bus:dispatch_listener")

    async def _dispatch(self, topic: str, event: "Event[Any]", listener: "Listener") -> None:
        try:
            if await listener.matches(event):
                self.logger.debug("Dispatching %s -> %r", topic, listener)
                await listener.handler(event)
        except asyncio.CancelledError:
            self.logger.debug("Listener dispatch cancelled (topic=%s, handler=%r)", topic, listener.handler_name)
            raise
        except Exception:
            self.logger.exception("Listener error (topic=%s, handler=%r)", topic, listener.handler_name)
        finally:
            # if once, remove after running
            if listener.once:
                self.remove_listener(listener)

    async def run_forever(self) -> None:
        """Worker loop that processes events from the stream."""

        async with self.starting():
            self.logger.debug("Waiting for Hassette ready event")
            await self.hassette.ready_event.wait()
            self.mark_ready(reason="Hassette is ready")

        try:
            async with self.stream:
                async for event_name, event_data in self.stream:
                    if self.hassette.shutdown_event.is_set():
                        self.logger.debug("Hassette is shutting down, exiting bus loop")
                        self.mark_not_ready(reason="Hassette is shutting down")
                        break
                    try:
                        await self.dispatch(event_name, event_data)
                    except Exception as e:
                        self.logger.exception("Error processing event: %s", e)
        except asyncio.CancelledError:
            self.logger.debug("EventBus service cancelled")
            self.mark_not_ready(reason="EventBus cancelled")
            await self.handle_stop()
        except Exception as e:
            await self.handle_crash(e)
            raise
        finally:
            await self.cleanup()


class Router:
    exact: dict[str, list["Listener"]]
    globs: dict[str, list["Listener"]]
    owners: dict[str, list["Listener"]]

    def __init__(self) -> None:
        # self.lock = asyncio.Lock()
        self.lock = FairAsyncRLock()
        self.exact = defaultdict(list)
        self.globs = defaultdict(list)  # keys contain glob chars
        self.owners = defaultdict(list)

    async def add_route(self, topic: str, listener: "Listener") -> None:
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

    async def remove_route(self, topic: str, predicate: Callable[["Listener"], bool]) -> None:
        """Remove a listener from the appropriate route based on whether it contains glob characters.

        Args:
            topic (str): The topic to remove the listener from.
            predicate (callable): A function that returns True for listeners to be removed.
        """

        bucket = self.globs if any(ch in topic for ch in GLOB_CHARS) else self.exact

        async with self.lock:
            listeners = bucket.get(topic)
            if not listeners:
                return

            removed: list[Listener] = []
            kept: list[Listener] = []

            for listener in listeners:
                if predicate(listener):
                    removed.append(listener)
                else:
                    kept.append(listener)

            if not removed:
                return

            if kept:
                bucket[topic] = kept
            else:
                bucket.pop(topic, None)

            removed_by_owner: dict[str, set[int]] = defaultdict(set)
            for listener in removed:
                removed_by_owner[listener.owner].add(listener.listener_id)

            for owner, removed_ids in removed_by_owner.items():
                owner_listeners = self.owners.get(owner)
                if not owner_listeners:
                    continue
                remaining = [x for x in owner_listeners if x.listener_id not in removed_ids]
                if remaining:
                    self.owners[owner] = remaining
                else:
                    self.owners.pop(owner, None)

    async def remove_listener(self, listener: "Listener") -> None:
        """Remove a specific listener from the router.

        Args:
            listener (Listener): The listener to remove.
        """

        def pred(x: "Listener") -> bool:
            return x.listener_id == listener.listener_id

        await self.remove_route(listener.topic, pred)

    async def remove_listener_by_id(self, topic: str, listener_id: int) -> None:
        """Remove a listener by its ID.

        Args:
            topic (str): The topic the listener is associated with.
            listener_id (int): The ID of the listener to remove.
        """

        def pred(x: "Listener") -> bool:
            return x.listener_id == listener_id

        await self.remove_route(topic, pred)

    async def get_matching_listeners(self, topic: str) -> list["Listener"]:
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

        async with self.lock:
            owner_listeners = self.owners.pop(owner, None)
            if not owner_listeners:
                return

            handled_topics = {listener.topic for listener in owner_listeners}
            for topic in handled_topics:
                bucket = self.globs if any(ch in topic for ch in GLOB_CHARS) else self.exact
                listeners = bucket.get(topic)
                if not listeners:
                    continue

                remaining = [listener for listener in listeners if listener.owner != owner]
                if remaining:
                    bucket[topic] = remaining
                else:
                    bucket.pop(topic, None)
