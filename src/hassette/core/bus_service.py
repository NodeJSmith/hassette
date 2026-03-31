import asyncio
import typing
from collections import defaultdict
from collections.abc import Awaitable, Callable
from fnmatch import fnmatch
from functools import cached_property
from typing import Any

from fair_async_rlock import FairAsyncRLock

from hassette.core.commands import InvokeHandler
from hassette.core.registration import ListenerRegistration
from hassette.events import Event, HassPayload
from hassette.resources.base import Resource, Service
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.glob_utils import GLOB_CHARS, matches_globs, split_exact_and_glob
from hassette.utils.hass_utils import split_entity_id, valid_entity_id
from hassette.utils.source_capture import capture_registration_source

if typing.TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream

    from hassette import Hassette
    from hassette.bus import Listener
    from hassette.core.command_executor import CommandExecutor
    from hassette.events import EventPayload


class BusService(Service):
    """EventBus service that handles event dispatching and listener management."""

    stream: "MemoryObjectReceiveStream[tuple[str, Event[Any]]]"
    """Stream to receive events from."""

    router: "Router"
    """Router to manage event listeners."""

    _excluded_domains_exact: set[str]
    _excluded_domain_globs: tuple[str, ...]
    _excluded_entities_exact: set[str]
    _excluded_entity_globs: tuple[str, ...]
    _has_exclusions: bool

    def __init__(
        self,
        hassette: "Hassette",
        *,
        stream: "MemoryObjectReceiveStream[tuple[str, Event[Any]]]",
        executor: "CommandExecutor",
        parent: "Resource | None" = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        self.stream = stream
        self._executor = executor
        self.router = Router()
        self._setup_exclusion_filters()

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
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
        """Add a listener to the bus.

        When the listener belongs to an app (has app_key), both route-add and
        DB registration happen in a single task. For ``once=True`` listeners,
        registration completes first to prevent orphan DB rows. For regular
        listeners, the route is added first for immediate event delivery.
        """
        if listener.app_key:
            return self.task_bucket.spawn(self._register_then_add_route(listener), name="bus:add_listener")
        return self.task_bucket.spawn(self.router.add_route(listener.topic, listener), name="bus:add_listener")

    async def _register_then_add_route(self, listener: "Listener") -> None:
        """Register a listener in the DB and add its route.

        For ``once=True`` listeners, DB registration completes before the route
        is added to prevent orphan rows (the listener could fire and be removed
        before registration finishes). For regular listeners, the route is added
        first so events are received immediately; ``db_id`` is set once DB
        registration completes, and dispatch uses the direct-invoke path until then.
        """
        source_location, registration_source = capture_registration_source()
        human_description: str | None = None
        if listener.predicate is not None and hasattr(listener.predicate, "summarize"):
            human_description = listener.predicate.summarize()  # pyright: ignore[reportAttributeAccessIssue]
        reg = ListenerRegistration(
            app_key=listener.app_key,
            instance_index=listener.instance_index,
            handler_method=listener.handler_name,
            topic=listener.topic,
            debounce=listener.debounce,
            throttle=listener.throttle,
            once=listener.once,
            priority=listener.priority,
            predicate_description=repr(listener.predicate) if listener.predicate else None,
            human_description=human_description,
            source_location=source_location,
            registration_source=registration_source,
        )
        if listener.once:
            listener.mark_registered(await self._executor.register_listener(reg))
            await self.router.add_route(listener.topic, listener)
        else:
            await self.router.add_route(listener.topic, listener)
            listener.mark_registered(await self._executor.register_listener(reg))

    def remove_listener(self, listener: "Listener") -> asyncio.Task[None]:
        """Remove a listener from the bus.

        Cancels any pending debounce task to prevent dangling references.
        """
        listener.cancel()
        return self._remove_listener_by_id(listener.topic, listener.listener_id)

    def _remove_listener_by_id(self, topic: str, listener_id: int) -> asyncio.Task[None]:
        """Remove a listener by its ID (internal — use remove_listener for full cleanup)."""
        return self.task_bucket.spawn(self.router.remove_listener_by_id(topic, listener_id), name="bus:remove_listener")

    def remove_listeners_by_owner(self, owner: str) -> asyncio.Task[None]:
        """Remove all listeners owned by a specific owner.

        Uses ``Router.clear_owner`` which atomically removes and returns listeners
        under a single lock, then cancels debounce tasks on the returned set.
        """

        async def _clear_and_cancel() -> None:
            removed = await self.router.clear_owner(owner)
            for listener in removed:
                listener.cancel()

        return self.task_bucket.spawn(_clear_and_cancel(), name="bus:remove_listeners_by_owner")

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

    async def dispatch(self, base_topic: str, event: "Event[Any]") -> None:
        """Dispatch an event to all matching listeners for the given topic."""

        if self._should_skip_event(base_topic, event):
            return

        if self._should_log_event(event):
            self.logger.debug("Event: %r", event)

        routes = self._expand_topics(base_topic, event)  # ordered: most specific -> least
        chosen: dict[int, tuple[str, Listener]] = {}  # listener_id -> (matched_route, listener)

        # Route first, then dedupe by "first match wins" because routes are ordered by specificity
        for route in routes:
            listeners = await self.router.get_topic_listeners(route)
            for listener in listeners:
                if listener.listener_id in chosen:
                    continue
                if listener.matches(event):
                    chosen[listener.listener_id] = (route, listener)

        if not chosen:
            return

        # group by route for logging
        listeners_by_route = defaultdict(list)
        for route, listener in chosen.values():
            listeners_by_route[route].append(listener)

        # loop over routes so we always log in order of specificity
        for route in routes:
            listeners = listeners_by_route.get(route)
            if not listeners:
                continue

            self.logger.debug("Dispatch fanout %s -> %s (%d listener(s))", base_topic, route, len(listeners))
            for listener in listeners:
                self.task_bucket.spawn(self._dispatch(route, event, listener), name="bus:dispatch_listener")

    def _expand_topics(self, topic: str, event: Event[Any]) -> list[str]:
        payload = event.payload
        if not isinstance(payload, HassPayload):
            return [topic]

        if payload.event_type != "state_changed":
            return [topic]

        # only specialize HA events you care about
        entity_id = payload.entity_id
        if not valid_entity_id(entity_id):
            self.logger.debug("Cannot expand topics for invalid entity_id: %r", entity_id)
            return [topic]

        domain, _ = split_entity_id(entity_id)
        return [
            f"{topic}.{entity_id}",  # hass.event.state_changed.light.office
            f"{topic}.{domain}.*",  # hass.event.state_changed.light.*
            topic,  # hass.event.state_changed
        ]

    async def _dispatch(self, topic: str, event: "Event[Any]", listener: "Listener") -> None:
        """Dispatch an event to a specific listener.

        Selects an invoke function based on whether the listener has a ``db_id``
        (tracked via CommandExecutor) or not (internal, error-catching only), then
        applies rate limiting and once-cleanup in a single shared path.

        Error contract of the invoke functions:
            - ``_make_internal_invoke_fn`` catches ``Exception`` subclasses (logs, does not
              propagate).  ``CancelledError`` (a ``BaseException``) still propagates
              intentionally — it signals shutdown and must reach the task runner.
            - ``_make_tracked_invoke_fn`` can propagate ``CancelledError`` — the
              ``CommandExecutor`` re-raises it after recording the cancellation.
            - The ``finally`` clause is safe because ``once + rate_limiting`` is
              prohibited by ``Listener.create()`` validation.  If that prohibition
              is ever relaxed, the ``finally`` must guard against ``CancelledError``
              to avoid removing a listener whose debounced handler hasn't fired yet.

        Concurrency model:
            Multiple spawned tasks may enter this method concurrently for the same
            listener (via ``task_bucket.spawn`` in ``dispatch``).  The once-guard
            (``_fired`` check-and-set) is owned by ``Listener.dispatch()`` — see its
            docstring for the atomicity argument.  The same single-threaded scheduling
            applies to the throttle check in ``RateLimiter._throttled_call``.
        """
        # New closure per dispatch: debounce always fires with the latest event's closure.
        # RateLimiter._debounced_call replaces (cancel-then-create) the previous task each
        # time, so the handler sees the event from the most recent dispatch call.
        if listener.db_id is None:
            invoke_fn = self._make_internal_invoke_fn(topic, event, listener)
        else:
            invoke_fn = self._make_tracked_invoke_fn(topic, event, listener)

        if listener.once and listener.rate_limiter:
            raise RuntimeError("once + rate_limiting is prohibited; see Listener.create() validation")
        try:
            await listener.dispatch(invoke_fn)
        finally:
            if listener.once:
                self.remove_listener(listener)

    def _make_internal_invoke_fn(
        self, topic: str, event: "Event[Any]", listener: "Listener"
    ) -> Callable[[], "Awaitable[None]"]:
        """Build an invoke function for internal (non-app) listeners.

        Wraps ``listener.invoke()`` in a try/except that logs and absorbs all
        exceptions, preventing handler failures from crashing the bus dispatch loop.
        """

        async def safe_invoke() -> None:
            try:
                await listener.invoke(event)
            except Exception:
                self.logger.exception("Internal handler error (topic=%s, handler=%r)", topic, listener)

        return safe_invoke

    def _make_tracked_invoke_fn(
        self, topic: str, event: "Event[Any]", listener: "Listener"
    ) -> Callable[[], "Awaitable[None]"]:
        """Build an invoke function for app-owned listeners with telemetry.

        The closure reads ``listener.db_id`` lazily at call time (not capture time)
        so that debounced handlers see the correct ``db_id`` after async registration
        completes.  If ``db_id`` is still ``None`` at fire time, falls back to direct
        invocation with error logging.

        Can propagate ``CancelledError`` — the ``CommandExecutor`` re-raises it after
        recording a cancellation record.
        """

        async def execute_fn() -> None:
            db_id = listener.db_id
            if db_id is None:
                self.logger.warning("Listener db_id not yet set, invoking directly without telemetry (topic=%s)", topic)
                try:
                    await listener.invoke(event)
                except Exception:
                    self.logger.exception("Handler error (topic=%s, handler=%r, db_id pending)", topic, listener)
                return
            cmd = InvokeHandler(listener=listener, event=event, topic=topic, listener_id=db_id)
            await self._executor.execute(cmd)

        return execute_fn

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

    def _should_skip_event(self, topic: str, event: "Event[EventPayload[Any]]") -> bool:
        """Determine if an event should be skipped based on exclusion filters."""
        if not event.payload:
            return False

        # if not an HA event, we should not skip it, we only filter HA events
        if not isinstance(event.payload, HassPayload):
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

            self.owners[listener.owner_id].append(listener)

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
                removed_by_owner[listener.owner_id].add(listener.listener_id)

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
            return list(self.owners.get(owner, ()))

    async def clear_owner(self, owner: str) -> list["Listener"]:
        """Remove all listeners associated with the given owner.

        Args:
            owner: The owner whose listeners should be removed.

        Returns:
            The list of removed listeners (for cleanup such as cancelling debounce tasks).
        """

        async with self.lock:
            owner_listeners = self.owners.pop(owner, None)
            if not owner_listeners:
                return []

            handled_topics = {listener.topic for listener in owner_listeners}
            for topic in handled_topics:
                bucket = self.globs if any(ch in topic for ch in GLOB_CHARS) else self.exact
                listeners = bucket.get(topic)
                if not listeners:
                    continue

                remaining = [listener for listener in listeners if listener.owner_id != owner]
                if remaining:
                    bucket[topic] = remaining
                else:
                    bucket.pop(topic, None)

            return owner_listeners
