import asyncio
import typing
from collections import defaultdict
from functools import cached_property
from typing import Any, ClassVar

from hassette.bus.duration_hold import DurationHoldManager
from hassette.bus.invocation import build_tracked_invoke_fn
from hassette.bus.listeners import Listener, Subscription
from hassette.bus.router import Router
from hassette.core.event_filter import EventFilter
from hassette.core.registration import ListenerRegistration
from hassette.core.registration_tracker import RegistrationTracker
from hassette.event_handling.predicates import summarize_top_level
from hassette.events import Event, HassPayload
from hassette.exceptions import ResourceNotReadyError
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.types.enums import RestartType
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.hass_utils import split_entity_id, valid_entity_id

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from anyio.streams.memory import MemoryObjectReceiveStream

    from hassette import Hassette
    from hassette.core.command_executor import CommandExecutor
    from hassette.events.hass.raw import HassStateDict
    from hassette.resources.base import Resource

_DISPATCH_STABILITY_SLEEP = 0.005
_DISPATCH_IDLE_DEFAULT_TIMEOUT = 2.0

_HASS_TOPIC_PREFIX = "hass."
_HASSETTE_TOPIC_PREFIX = "hassette."


class BusService(Service):
    """EventBus service that handles event dispatching and listener management."""

    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.PERMANENT,
        budget_intensity=2,
        budget_period_seconds=30,
    )

    stream: "MemoryObjectReceiveStream[tuple[str, Event[Any]]]"
    """Stream to receive events from."""

    router: "Router"
    """Router to manage event listeners."""

    _reg_tracker: RegistrationTracker
    """Tracks pending DB registration tasks per app_key for await barrier support."""

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
        self._reg_tracker = RegistrationTracker()
        # Dispatch tracking for deterministic drain in test harnesses.
        self._dispatch_pending: int = 0
        self._dispatch_idle_event: asyncio.Event = asyncio.Event()
        self._dispatch_idle_event.set()  # starts idle

        self._event_filter = EventFilter(
            excluded_domains=hassette.config.bus_excluded_domains,
            excluded_entities=hassette.config.bus_excluded_entities,
            logger=self.logger,
        )

        # Lambda — must remain callable so hot-reload picks up config changes at fire time.
        self._config_resolver: Callable[[], float | None] = (
            lambda: self.hassette.config.lifecycle.event_handler_timeout_seconds
        )

        self._duration_hold = DurationHoldManager(
            executor=self._executor,
            config_resolver=self._config_resolver,
            state_reader=self._read_entity_state,
            remove_listener=self.remove_listener,
            router=self.router,
            task_bucket=self.task_bucket,
            logger=self.logger,
        )

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.bus_service

    @cached_property
    def config_log_all_events(self) -> bool:
        """Return whether to log all events."""
        return self.hassette.config.logging.all_events

    def _on_dispatch_done(self, _task: asyncio.Task[Any]) -> None:
        """Callback for dispatch task completion — decrements pending counter."""
        if self._dispatch_pending <= 0:
            self.logger.warning("_dispatch_pending underflow detected (was %d); resetting to 0", self._dispatch_pending)
            self._dispatch_pending = 0
            self._dispatch_idle_event.set()
            return
        self._dispatch_pending -= 1
        if self._dispatch_pending == 0:
            self._dispatch_idle_event.set()

    def add_listener(self, listener: "Listener") -> "asyncio.Task[None]":
        """Add a listener to the bus.

        Route insertion is synchronous. DB registration is spawned as a background
        task. For duration listeners, wires the timer and delegates cancel listener
        creation to ``DurationHoldManager``. Immediate-fire tasks are tracked in
        ``_dispatch_pending`` so ``await_dispatch_idle`` drains them.

        Returns:
            The DB registration task (used by ``Bus._on_internal`` to populate
            ``Subscription.registration_task``).
        """
        if listener.duration_config is not None and listener.duration_config.duration is not None:

            def make_cancel_sub() -> Subscription:
                return self._duration_hold.create_cancel_listener(listener)

            def on_timer_cancel() -> None:
                self._duration_hold.decrement_timers_active()

            listener.duration_config.attach_timer(
                task_bucket=self.task_bucket,
                owner_id=listener.identity.owner_id,
                create_cancel_sub=make_cancel_sub,
                on_cancel=on_timer_cancel,
            )

        # Sync: insert route immediately — listener is routable before this returns.
        self.router.add_route(listener.topic, listener)

        # Async: spawn DB registration as a background task.
        app_key = listener.identity.app_key or listener.identity.owner_id
        reg = self._build_registration(listener)
        task = self.task_bucket.spawn(self._register_in_db(listener, reg), name="bus:register_in_db")
        self._reg_tracker.prune_and_track(app_key, task)

        if listener.duration_config is not None and listener.duration_config.immediate:
            self._dispatch_pending += 1
            self._dispatch_idle_event.clear()
            immediate_task = self.task_bucket.spawn(
                self._duration_hold.immediate_fire_task(listener),
                name="bus:immediate_fire",
            )
            immediate_task.add_done_callback(self._on_dispatch_done)

        return task

    async def drain_framework_registrations(self) -> None:
        """Drain all pending framework registration tasks."""
        await self._reg_tracker.drain_framework_keys(self.await_registrations_complete)

    def _build_registration(self, listener: Listener) -> ListenerRegistration:
        """Build a ``ListenerRegistration`` struct from listener identity and options."""
        source_location = listener.identity.source_location
        registration_source: str | None = listener.identity.registration_source or None
        human_description: str | None = None
        if listener.predicate is not None:
            human_description = summarize_top_level(listener.predicate)
        return ListenerRegistration(
            app_key=listener.identity.app_key,
            instance_index=listener.identity.instance_index,
            handler_method=listener.identity.handler_name,
            topic=listener.topic,
            debounce=listener.options.debounce,
            throttle=listener.options.throttle,
            once=listener.options.once,
            priority=listener.options.priority,
            predicate_description=repr(listener.predicate) if listener.predicate else None,
            human_description=human_description,
            source_location=source_location,
            registration_source=registration_source,
            name=listener.identity.name,
            source_tier=listener.identity.source_tier,
            immediate=listener.duration_config.immediate if listener.duration_config else False,
            duration=listener.duration_config.duration if listener.duration_config else None,
            entity_id=listener.duration_config.entity_id if listener.duration_config else None,
        )

    async def _register_in_db(self, listener: Listener, reg: ListenerRegistration) -> None:
        """Persist a listener to the database for telemetry.

        Routing has already completed synchronously before this is spawned.
        Suppresses both ``CancelledError`` and ``Exception`` so ``registration_task``
        always resolves cleanly. A failure here does not affect event delivery.
        """
        try:
            listener.mark_registered(await self._executor.register_listener(reg))
        except asyncio.CancelledError:  # noqa: ASYNC103 — deliberately suppressed per AC#6
            self.logger.warning(
                "DB registration cancelled for owner_id=%s topic=%s; "
                "listener will run without telemetry until next restart",
                listener.identity.owner_id,
                listener.topic,
            )
        except Exception:
            self.logger.exception(
                "Failed to register listener in DB for owner_id=%s topic=%s; "
                "listener will run without telemetry until next restart",
                listener.identity.owner_id,
                listener.topic,
            )

    def remove_listener(self, listener: "Listener") -> None:
        """Synchronously cancel and remove a listener from the routing table."""
        listener.cancel()
        self.router.remove_listener_by_id(listener.topic, listener.listener_id)

    def remove_listeners_by_owner(self, owner: str) -> None:
        """Remove all listeners owned by a specific owner synchronously."""
        removed = self.router.clear_owner(owner)
        for listener in removed:
            listener.cancel()

    def get_listeners_by_owner(self, owner: str) -> list["Listener"]:
        """Get all listeners owned by a specific owner."""
        return self.router.get_listeners_by_owner(owner)

    async def await_registrations_complete(self, app_key: str) -> None:
        """Wait for all pending DB registration tasks for an app to complete.

        Has a configurable timeout (``config.registration_await_timeout``, default 30s).
        Tasks that error complete with ``db_id = None`` — listener runs without telemetry.
        """
        timeout = float(self.hassette.config.lifecycle.registration_await_timeout)
        await self._reg_tracker.await_complete(app_key, timeout=timeout, logger=self.logger)

    def _should_log_event(self, event: "Event[Any]") -> bool:
        """Determine if an event should be logged based on its type."""
        if not event.payload:
            return False

        if self.config_log_all_events:
            return True

        if self.hassette.config.logging.all_hass_events and event.topic.startswith(_HASS_TOPIC_PREFIX):
            return True

        if self.hassette.config.logging.all_hassette_events and event.topic.startswith(_HASSETTE_TOPIC_PREFIX):
            return True

        return False

    async def dispatch(self, base_topic: str, event: "Event[Any]") -> None:
        """Dispatch an event to all matching listeners for the given topic."""

        if self._event_filter.should_skip(base_topic, event):
            return

        if self._should_log_event(event):
            self.logger.debug("Event: %r", event)

        routes = self._expand_topics(base_topic, event)  # ordered: most specific -> least
        chosen: dict[int, tuple[str, Listener]] = {}  # listener_id -> (matched_route, listener)

        # Route first, then dedupe by "first match wins" because routes are ordered by specificity
        for route in routes:
            listeners = self.router.get_topic_listeners(route)
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
                self._dispatch_pending += 1
                self._dispatch_idle_event.clear()
                task = self.task_bucket.spawn(self._dispatch(route, event, listener), name="bus:dispatch_listener")
                task.add_done_callback(self._on_dispatch_done)

    def _expand_topics(self, topic: str, event: Event[Any]) -> list[str]:
        payload = event.payload
        if not isinstance(payload, HassPayload):
            return [topic]

        if payload.event_type != "state_changed":
            return [topic]

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

    def _read_entity_state(self, entity_id: str) -> "HassStateDict | None":
        """Read entity state from StateProxy; returns None on any error.

        Absorbs ``ResourceNotReadyError`` and unexpected exceptions so the
        caller (DurationHoldManager) never needs to handle state-read failures.
        """
        try:
            state_proxy = self.hassette._state_proxy
            if state_proxy is None:
                self.logger.debug("read_entity_state: StateProxy not available for entity %s, skipping", entity_id)
                return None
            current_state = state_proxy.states.get(entity_id)
            if current_state is None:
                self.logger.debug("read_entity_state: entity %s not found in StateProxy, skipping", entity_id)
                return None
            return current_state
        except ResourceNotReadyError as exc:
            self.logger.error(
                "read_entity_state: ResourceNotReadyError for entity %s (sequencing violation).",
                entity_id,
                exc_info=exc,
            )
            return None
        except Exception as exc:
            self.logger.warning(
                "read_entity_state: unexpected error reading state for entity %s.",
                entity_id,
                exc_info=exc,
            )
            return None

    @property
    def duration_timers_active(self) -> int:
        """Number of currently active duration timers."""
        return self._duration_hold.duration_timers_active

    async def _dispatch(self, topic: str, event: "Event[Any]", listener: "Listener") -> None:
        """Dispatch an event to a specific listener.

        Builds an invoke_fn via ``build_tracked_invoke_fn``. Duration listeners
        delegate to ``DurationHoldManager.start_duration_timer``; non-duration
        listeners dispatch inline with ``once`` removal in a ``finally`` block.
        """
        # invoke_fn captures the original triggering event. Duration timer callbacks
        # re-verify current state via hold predicates but dispatch via this invoke_fn
        # — the handler receives the event that started the timer.
        invoke_fn = build_tracked_invoke_fn(listener, event, topic, self._executor, self._config_resolver)

        if listener.duration_config is not None and listener.duration_config.duration is not None:
            if listener.is_cancelled:
                return

            duration_config = listener.duration_config
            entity_id = duration_config.entity_id
            if not entity_id:
                self.logger.error(
                    "duration_fire: listener has no entity_id — construction invariant violated. "
                    "Listener owner=%s topic=%s",
                    listener.identity.owner_id,
                    listener.topic,
                )
                return

            self._duration_hold.start_duration_timer(listener, entity_id, duration_config, invoke_fn)
            return

        # Non-duration path (unchanged behavior).
        try:
            await listener.invoker.dispatch(invoke_fn)
        finally:
            if listener.options.once:
                self.remove_listener(listener)

    async def before_initialize(self) -> None:
        await self.hassette.ready_event.wait()

    @property
    def is_dispatch_idle(self) -> bool:
        return self._dispatch_idle_event.is_set()

    @property
    def dispatch_pending_count(self) -> int:
        return self._dispatch_pending

    async def await_dispatch_idle(self, *, timeout: float = _DISPATCH_IDLE_DEFAULT_TIMEOUT) -> None:
        """Wait until all dispatched handler tasks have completed.

        Polls with a stability check to handle in-transit events from the anyio
        memory channel pipeline. Duration timer callbacks are NOT tracked here.

        Raises:
            TimeoutError: If dispatch tasks are still running after ``timeout``.
        """
        deadline = asyncio.get_running_loop().time() + timeout

        def timeout_error() -> TimeoutError:
            return TimeoutError(
                f"BusService dispatch tasks did not complete within {timeout}s "
                f"({self._dispatch_pending} dispatch tasks still pending)"
            )

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise timeout_error()
            try:
                await asyncio.wait_for(self._dispatch_idle_event.wait(), timeout=remaining)
            except TimeoutError:
                raise timeout_error() from None

            # Stability check: yield to let any in-transit events from the
            # anyio memory channel reach serve() → dispatch(). If idle_event
            # is still set after the yield, no new dispatches were triggered.
            await asyncio.sleep(_DISPATCH_STABILITY_SLEEP)
            if self._dispatch_idle_event.is_set():
                break

    async def serve(self) -> None:
        """Worker loop that processes events from the stream."""

        async with self.stream:
            self.mark_ready(reason="Stream opened")
            async for event_name, event_data in self.stream:
                if self.shutdown_event.is_set():
                    active_timers = self._duration_hold.duration_timers_active
                    if active_timers > 0:
                        self.logger.info(
                            "Shutdown: %d active duration timer(s) will be cancelled",
                            active_timers,
                        )
                    self.logger.debug("Hassette is shutting down, exiting bus loop")
                    self.mark_not_ready(reason="Hassette is shutting down")
                    break
                try:
                    await self.dispatch(event_name, event_data)
                except Exception as e:
                    self.logger.exception("Error processing event: %s", e)
