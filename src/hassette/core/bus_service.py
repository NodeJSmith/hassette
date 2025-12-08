import asyncio
import itertools
import typing
from collections import defaultdict
from collections.abc import Callable
from fnmatch import fnmatch
from functools import cached_property
from typing import Any

from fair_async_rlock import FairAsyncRLock

from hassette.resources.base import Service
from hassette.utils.glob_utils import GLOB_CHARS, matches_globs, split_exact_and_glob

if typing.TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream

    from hassette import Hassette
    from hassette.bus import Listener
    from hassette.events import Event


class BusService(Service):
    """EventBus service that handles event dispatching and listener management."""

    stream: "MemoryObjectReceiveStream[tuple[str, Event[Any]]]"
    """Stream to receive events from."""

    listener_seq: itertools.count
    """Sequence generator for listener IDs."""

    router: "Router"
    """Router to manage event listeners."""

    _excluded_domains_exact: set[str]
    _excluded_domain_globs: tuple[str, ...]
    _excluded_entities_exact: set[str]
    _excluded_entity_globs: tuple[str, ...]
    _has_exclusions: bool

    @classmethod
    def create(cls, hassette: "Hassette", stream: "MemoryObjectReceiveStream[tuple[str, Event[Any]]]"):
        inst = cls(hassette, parent=hassette)
        inst.stream = stream
        inst.listener_seq = itertools.count(1)
        inst.router = Router()
        inst._setup_exclusion_filters()

        return inst

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.bus_service_log_level

    @cached_property
    def config_log_all_events(self) -> bool:
        """Return whether to log all events."""
        return self.hassette.config.log_all_events

    def _log_task_result(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return

        exc = task.exception()
        if exc:
            self.logger.error("Bus background task failed", exc_info=exc)

    def add_listener(self, listener: "Listener") -> asyncio.Task[None]:
        """Add a listener to the bus."""
        return self.task_bucket.spawn(self.router.add_route(listener.topic, listener), name="bus:add_listener")

    def remove_listener(self, listener: "Listener") -> asyncio.Task[None]:
        """Remove a listener from the bus."""
        return self.remove_listener_by_id(listener.topic, listener.listener_id)

    def remove_listener_by_id(self, topic: str, listener_id: int) -> asyncio.Task[None]:
        """Remove a listener by its ID."""
        return self.task_bucket.spawn(self.router.remove_listener_by_id(topic, listener_id), name="bus:remove_listener")

    def remove_listeners_by_owner(self, owner: str) -> asyncio.Task[None]:
        """Remove all listeners owned by a specific owner."""
        return self.task_bucket.spawn(self.router.clear_owner(owner), name="bus:remove_listeners_by_owner")

    def get_listeners_by_owner(self, owner: str) -> asyncio.Task[list["Listener"]]:
        """Get all listeners owned by a specific owner."""
        return self.task_bucket.spawn(self.router.get_listeners_by_owner(owner), name="bus:get_listeners_by_owner")

    def _should_log_event(self, event: "Event[Any]") -> bool:
        """Determine if an event should be logged based on its type."""
        if not event.payload:
            return False

        if self.config_log_all_events:
            return True

        if self.hassette.config.log_all_hass_events and event.topic.startswith("hass."):
            return True

        if self.hassette.config.log_all_hassette_events and event.topic.startswith("hassette."):
            return True

        return False

    async def dispatch(self, topic: str, event: "Event[Any]") -> None:
        """Dispatch an event to all matching listeners for the given topic."""

        if self._should_skip_event(topic, event):
            return

        targets = await self._get_matching_listeners(topic, event)

        if self._should_log_event(event):
            self.logger.debug("Event: %r", event)

        if not targets:
            return

        self.logger.debug("Dispatching %s to %d listeners", topic, len(targets))
        for listener in targets:
            self.task_bucket.spawn(self._dispatch(topic, event, listener), name="bus:dispatch_listener")

    async def _get_matching_listeners(self, topic: str, event: "Event[Any]") -> list["Listener"]:
        """Get all listeners that match the given event."""
        all_listeners = await self.router.get_topic_listeners(topic)
        return [listener for listener in all_listeners if await listener.matches(event)]

    async def _dispatch(self, topic: str, event: "Event[Any]", listener: "Listener") -> None:
        """Dispatch an event to a specific listener."""

        # we are assuming matches() has already been called
        try:
            self.logger.debug("Dispatching %s -> %r", topic, listener)
            await listener.invoke(event)
        except asyncio.CancelledError:
            self.logger.debug("Listener dispatch cancelled (topic=%s, handler=%r)", topic, listener.handler_name)
            raise
        except Exception:
            self.logger.exception("Listener error (topic=%s, handler=%r)", topic, listener.handler_name)
        finally:
            # if once, remove after running
            if listener.once:
                self.remove_listener(listener)

    async def before_initialize(self) -> None:
        self.logger.debug("Waiting for Hassette ready event")
        await self.hassette.ready_event.wait()

    async def serve(self) -> None:
        """Worker loop that processes events from the stream."""

        async with self.stream:
            self.mark_ready(reason="Stream opened")
            async for event_name, event_data in self.stream:
                if self.shutdown_event.is_set():
                    self.logger.debug("Hassette is shutting down, exiting bus loop")
                    self.mark_not_ready(reason="Hassette is shutting down")
                    break
                try:
                    await self.dispatch(event_name, event_data)
                except Exception as e:
                    self.logger.exception("Error processing event: %s", e)

    def _setup_exclusion_filters(self) -> None:
        domains = self.hassette.config.bus_excluded_domains or ()
        entities = self.hassette.config.bus_excluded_entities or ()

        self._excluded_domains_exact, self._excluded_domain_globs = split_exact_and_glob(domains)
        self._excluded_entities_exact, self._excluded_entity_globs = split_exact_and_glob(entities)

        self._has_exclusions = bool(
            self._excluded_domains_exact
            or self._excluded_domain_globs
            or self._excluded_entities_exact
            or self._excluded_entity_globs
        )

        if self._has_exclusions:
            self.logger.debug(
                "Configured bus exclusions: domains=%s domain_globs=%s entities=%s entity_globs=%s",
                sorted(self._excluded_domains_exact),
                self._excluded_domain_globs,
                sorted(self._excluded_entities_exact),
                self._excluded_entity_globs,
            )

    def _should_skip_event(self, topic: str, event: "Event[Any]") -> bool:
        """Determine if an event should be skipped based on exclusion filters."""
        if not event.payload:
            return False

        payload = event.payload
        entity_id = getattr(payload, "entity_id", None) if payload else None
        domain = getattr(payload, "domain", None) if payload else None

        try:
            if (
                payload.event_type == "call_service"
                and payload.data.domain == "system_log"
                and payload.data.service_data.get("level") == "debug"
            ):
                return True
        except Exception:
            pass

        if not self._has_exclusions:
            return False

        if not entity_id or not domain:
            return False

        if typing.TYPE_CHECKING:
            assert entity_id is not None
            assert isinstance(entity_id, str)
            assert domain is not None
            assert isinstance(domain, str)

        if isinstance(entity_id, str):
            if entity_id in self._excluded_entities_exact or matches_globs(entity_id, self._excluded_entity_globs):
                self.logger.debug("Skipping dispatch for %s due to entity exclusion (%s)", topic, entity_id)
                return True
            if domain is None and "." in entity_id:
                domain = entity_id.split(".", 1)[0]

        if isinstance(domain, str) and domain:
            if domain in self._excluded_domains_exact or matches_globs(domain, self._excluded_domain_globs):
                self.logger.debug("Skipping dispatch for %s due to domain exclusion (%s)", topic, domain)
                return True

        return False


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
            topic: The topic to add the listener to.
            listener: The listener to add.
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
            topic: The topic to remove the listener from.
            predicate: A function that returns True for listeners to be removed.
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
            listener: The listener to remove.
        """

        def pred(x: "Listener") -> bool:
            return x.listener_id == listener.listener_id

        await self.remove_route(listener.topic, pred)

    async def remove_listener_by_id(self, topic: str, listener_id: int) -> None:
        """Remove a listener by its ID.

        Args:
            topic: The topic the listener is associated with.
            listener_id: The ID of the listener to remove.
        """

        def pred(x: "Listener") -> bool:
            return x.listener_id == listener_id

        await self.remove_route(topic, pred)

    async def get_topic_listeners(self, topic: str) -> list["Listener"]:
        """Get all listeners that match the given topic.

        Args:
            topic: The topic to match against.

        Returns:
            A list of listeners that match the topic, sorted by priority (highest first).
        """
        async with self.lock:
            out: list[Listener] = []
            out.extend(self.exact.get(topic, ()))

            for k, listener in self.globs.items():
                if fnmatch(topic, k):
                    out.extend(listener)

            # de-dup preserving order
            seen: set[int] = set()
            unique: list[Listener] = []
            for listener in out:
                if id(listener) not in seen:
                    seen.add(id(listener))
                    unique.append(listener)

            # Sort by priority (highest first)
            unique.sort(key=lambda x: x.priority, reverse=True)
            return unique

    async def get_listeners_by_owner(self, owner: str) -> list["Listener"]:
        """Get all listeners associated with the given owner.

        Args:
            owner: The owner whose listeners should be retrieved.

        Returns:
            A list of listeners associated with the owner.
        """
        async with self.lock:
            return self.owners.get(owner, [])

    async def clear_owner(self, owner: str) -> None:
        """Remove all listeners associated with the given owner.

        Args:
            owner: The owner whose listeners should be removed.
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
