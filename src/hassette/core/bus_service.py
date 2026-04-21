import asyncio
import typing
from collections import defaultdict
from collections.abc import Awaitable, Callable
from fnmatch import fnmatch
from functools import cached_property
from typing import Any
from uuid import uuid4

from fair_async_rlock import FairAsyncRLock

import hassette.utils.date_utils as _date_utils
from hassette.bus.duration_timer import DurationTimer
from hassette.bus.listeners import Listener, Subscription
from hassette.core.commands import InvokeHandler
from hassette.core.registration import ListenerRegistration
from hassette.core.registration_tracker import RegistrationTracker
from hassette.events import Event, HassPayload
from hassette.events.base import HassContext
from hassette.events.hass.hass import RawStateChangeEvent, RawStateChangePayload
from hassette.exceptions import ResourceNotReadyError
from hassette.resources.base import Resource, Service
from hassette.types import Topic
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.glob_utils import GLOB_CHARS, matches_globs, split_exact_and_glob
from hassette.utils.hass_utils import split_entity_id, valid_entity_id

if typing.TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream

    from hassette import Hassette
    from hassette.core.command_executor import CommandExecutor
    from hassette.events import EventPayload
    from hassette.events.hass.raw import HassStateDict


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
        self._duration_timers_active: int = 0
        self._setup_exclusion_filters()

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.bus_service_log_level

    @cached_property
    def config_log_all_events(self) -> bool:
        """Return whether to log all events."""
        return self.hassette.config.log_all_events

    def _on_dispatch_done(self, _task: asyncio.Task[Any]) -> None:
        """Callback for dispatch task completion — decrements pending counter."""
        self._dispatch_pending -= 1
        if self._dispatch_pending <= 0:
            self._dispatch_pending = 0  # guard against underflow
            self._dispatch_idle_event.set()

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

        Registration tasks are tracked per ``app_key`` so
        ``await_registrations_complete()`` can drain them before reconciliation.

        For duration listeners, wires the ``_duration_timer`` as the single
        authority — ``Listener.create()`` does not construct it.  Uses
        ``listener.hold_predicate`` (state-value predicates only) for cancel
        evaluation, falling back to ``listener.predicate`` if hold predicates
        were not provided.
        """
        if listener.duration is not None and listener.entity_id:

            def make_cancel_sub() -> Subscription:
                return self._create_cancel_listener(listener)

            def on_timer_cancel() -> None:
                self._duration_timers_active -= 1

            listener._duration_timer = DurationTimer(
                task_bucket=self.task_bucket,
                duration=listener.duration,
                predicates=listener.hold_predicate or listener.predicate,
                entity_id=listener.entity_id,
                owner_id=listener.owner_id,
                create_cancel_sub=make_cancel_sub,
                on_cancel=on_timer_cancel,
            )

        app_key = listener.app_key or listener.owner_id
        task = self.task_bucket.spawn(self._register_then_add_route(listener), name="bus:add_listener")
        self._reg_tracker.prune_and_track(app_key, task)
        return task

    def _create_cancel_listener(self, main_listener: "Listener") -> Subscription:
        """Create and register a cancellation listener for a duration timer.

        The cancellation listener monitors the same entity as ``main_listener``
        and calls ``DurationTimer.evaluate_cancel_event()`` on each incoming
        ``state_changed`` event.  The old_state stripping and predicate
        re-evaluation are handled inside ``evaluate_cancel_event()``.

        Route insertion is spawned as a task and tracked so that
        ``await_dispatch_idle()`` waits for it.  The fire-time recheck in
        ``on_duration_fire`` is the definitive correctness gate for the
        one-event-loop-iteration window before route insertion completes.

        Properties:
        - Uses ``source_tier="framework"`` (filtered from user-facing counts).
        - Uses the same ``owner_id`` as the main listener (cleaned up together).
        - Bypasses DB registration (no ``ListenerRegistration`` row).

        Args:
            main_listener: The duration listener whose timer this subscription guards.

        Returns:
            A ``Subscription`` whose ``cancel()`` removes the listener from Router.
        """
        assert main_listener.entity_id is not None, "duration listener must have entity_id"
        assert main_listener._duration_timer is not None, "duration listener must have _duration_timer"

        duration_timer = main_listener._duration_timer

        async def cancel_handler(event: "Event[Any]") -> None:
            duration_timer.evaluate_cancel_event(event)

        cancel_listener = Listener.create(
            task_bucket=self.task_bucket,
            owner_id=main_listener.owner_id,
            topic=f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{main_listener.entity_id}",
            handler=cancel_handler,
            source_tier="framework",
        )

        async def _add_cancel_route() -> None:
            await self.router.add_route(cancel_listener.topic, cancel_listener)

        self._dispatch_pending += 1
        self._dispatch_idle_event.clear()
        task = self.task_bucket.spawn(_add_cancel_route(), name="bus:add_cancel_listener")
        task.add_done_callback(self._on_dispatch_done)

        def unsubscribe() -> None:
            cancel_listener.cancel()
            self._remove_listener_by_id(cancel_listener.topic, cancel_listener.listener_id)

        return Subscription(cancel_listener, unsubscribe)

    async def drain_framework_registrations(self) -> None:
        """Drain all pending framework registration tasks.

        Delegates to ``RegistrationTracker.drain_framework_keys()`` which
        iterates a snapshot of keys and calls ``await_registrations_complete``
        for any key that matches ``is_framework_key()``.
        """
        await self._reg_tracker.drain_framework_keys(self.await_registrations_complete)

    async def _register_then_add_route(self, listener: Listener) -> None:
        """Register a listener in the DB and add its route.

        For ``once=True`` listeners, DB registration completes before the route
        is added to prevent orphan rows (the listener could fire and be removed
        before registration finishes). For regular listeners, the route is added
        first so events are received immediately; ``db_id`` is set once DB
        registration completes, and invocations before then produce orphan records.

        When ``listener.immediate`` is True, spawns a separate task after route
        insertion and DB registration to fire the handler with the current entity
        state.  This is decoupled from registration to prevent serialization of
        N startup state reads.
        """
        source_location = listener.source_location
        registration_source: str | None = listener.registration_source or None
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
            name=listener.name,
            source_tier=listener.source_tier,
            immediate=listener.immediate,
            duration=listener.duration,
            entity_id=listener.entity_id,
        )
        if listener.once:
            try:
                listener.mark_registered(await self._executor.register_listener(reg))
            except Exception:
                self.logger.exception(
                    "Failed to register once=True listener in DB for owner_id=%s topic=%s; "
                    "listener will fire once and produce an orphan invocation record",
                    listener.owner_id,
                    listener.topic,
                )
            await self.router.add_route(listener.topic, listener)
        else:
            await self.router.add_route(listener.topic, listener)
            try:
                listener.mark_registered(await self._executor.register_listener(reg))
            except Exception:
                self.logger.exception(
                    "Failed to register listener in DB for owner_id=%s topic=%s; "
                    "listener will run without telemetry until next restart",
                    listener.owner_id,
                    listener.topic,
                )

        if listener.immediate and listener.entity_id:
            self._dispatch_pending += 1
            self._dispatch_idle_event.clear()
            task = self.task_bucket.spawn(
                self._immediate_fire_task(listener),
                name="bus:immediate_fire",
            )
            task.add_done_callback(self._on_dispatch_done)

    def _make_synthetic_state_event(self, entity_id: str, current_state: "HassStateDict") -> RawStateChangeEvent:
        """Build a synthetic RawStateChangeEvent with old_state=None."""
        return RawStateChangeEvent(
            topic=f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{entity_id}",
            payload=HassPayload(
                event_type="state_changed",
                data=RawStateChangePayload(
                    entity_id=entity_id,
                    old_state=None,
                    new_state=current_state,
                ),
                origin="LOCAL",
                time_fired=_date_utils.now(),
                context=HassContext(id=str(uuid4()), parent_id=None, user_id=None),
            ),
        )

    def _hold_matches(self, listener: Listener, event: "Event[Any]") -> bool:
        """Check hold predicates (state-value only) against an event.

        Falls back to ``listener.matches()`` when no hold predicate is set.
        """
        hold_pred = listener.hold_predicate
        if hold_pred is None:
            return listener.matches(event)
        return hold_pred(event)

    async def _immediate_fire_task(self, listener: Listener) -> None:
        """Fire a handler immediately with the current entity state.

        Called as a separate spawned task (not inline) after route insertion and
        DB registration complete.  Reads the current entity state from StateProxy
        via direct dict access — no retries, no HTTP, no exception path.

        This implements the ``immediate=True`` semantics: if the entity already
        exists in the cache at registration time the handler fires once with a
        synthetic ``RawStateChangeEvent`` whose ``old_state`` is None.

        Error contract:
            - If the entity is not found → return silently, log at DEBUG.
            - ``ResourceNotReadyError`` (should not occur; StateProxy is ready before
              apps' ``on_initialize`` runs) → log at ERROR as a sequencing violation.
            - Any other exception → log at WARNING; immediate fire becomes a no-op.
        """
        entity_id = listener.entity_id
        if not entity_id:
            self.logger.error(
                "immediate_fire: listener has no entity_id — construction invariant violated. "
                "Listener owner=%s topic=%s",
                listener.owner_id,
                listener.topic,
            )
            return

        try:
            state_proxy = self.hassette._state_proxy
            if state_proxy is None:
                self.logger.debug(
                    "immediate_fire: StateProxy not available for entity %s, skipping",
                    entity_id,
                )
                return

            current_state = state_proxy.states.get(entity_id)
            if current_state is None:
                self.logger.debug(
                    "immediate_fire: entity %s not found in StateProxy, skipping",
                    entity_id,
                )
                return

            synthetic_event = self._make_synthetic_state_event(entity_id, current_state)

            if not listener.matches(synthetic_event):
                return

            # FR4: handler receives the original triggering event (the synthetic event
            # built from current state at registration time).  The recheck at fire time
            # validates current state but does not change what event the handler receives.
            invoke_fn = self._make_tracked_invoke_fn(synthetic_event.topic, synthetic_event, listener)

            if listener.duration is not None and listener._duration_timer is not None:
                elapsed = 0.0
                if not listener.is_attribute_listener:
                    last_changed_raw = current_state.get("last_changed")
                    if isinstance(last_changed_raw, str):
                        last_changed = _date_utils.convert_datetime_str_to_system_tz(last_changed_raw)
                        if last_changed is not None:
                            now_dt = _date_utils.now()
                            raw_elapsed = (now_dt - last_changed).in_seconds()
                            elapsed = max(0.0, min(raw_elapsed, listener.duration))

                if elapsed >= listener.duration:
                    try:
                        await listener.dispatch(invoke_fn)
                    finally:
                        if listener.once:
                            self.remove_listener(listener)
                else:
                    remaining = listener.duration - elapsed
                    self.logger.debug(
                        "immediate_fire: entity %s elapsed=%.2fs, starting duration timer for remaining=%.2fs",
                        entity_id,
                        elapsed,
                        remaining,
                    )

                    async def on_duration_fire_immediate() -> None:
                        self._duration_timers_active -= 1
                        current = self._read_entity_state(entity_id)
                        if current is None:
                            if listener.once:
                                self.remove_listener(listener)
                            return

                        recheck_event = self._make_synthetic_state_event(entity_id, current)
                        if not self._hold_matches(listener, recheck_event):
                            if listener.once:
                                self.remove_listener(listener)
                            return

                        try:
                            await listener.dispatch(invoke_fn)
                        finally:
                            if listener.once:
                                self.remove_listener(listener)

                    self._duration_timers_active += 1
                    listener._duration_timer.start(on_duration_fire_immediate, override_duration=remaining)
                return

            try:
                await listener.dispatch(invoke_fn)
            finally:
                if listener.once:
                    self.remove_listener(listener)

        except ResourceNotReadyError as exc:
            self.logger.error(
                "immediate_fire: ResourceNotReadyError for entity %s — "
                "StateProxy is not ready at registration time; this is a sequencing invariant violation. "
                "Listener owner=%s topic=%s",
                entity_id,
                listener.owner_id,
                listener.topic,
                exc_info=exc,
            )
        except Exception as exc:
            self.logger.warning(
                "immediate_fire: unexpected error for entity %s, "
                "immediate fire will not occur. Listener owner=%s topic=%s",
                entity_id,
                listener.owner_id,
                listener.topic,
                exc_info=exc,
            )

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

    async def await_registrations_complete(self, app_key: str) -> None:
        """Wait for all pending DB registration tasks for an app to complete.

        Called by ``AppLifecycleService.initialize_instances()`` before reconciliation
        to ensure all listener ``db_id`` values are populated. Tasks that error
        (DB unavailable) complete with ``db_id = None`` — the listener is excluded
        from ``live_listener_ids`` but not actively retired.

        Has a configurable timeout (``config.registration_await_timeout``, default 30s)
        to prevent indefinite hangs if the DB write queue stalls.

        Args:
            app_key: The app key whose pending registration tasks to await.
        """
        timeout = float(self.hassette.config.registration_await_timeout)
        await self._reg_tracker.await_complete(app_key, timeout=timeout, logger=self.logger)

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

    def _read_entity_state(self, entity_id: str) -> "HassStateDict | None":
        """Read entity state from StateProxy (in-memory, no HTTP)."""
        state_proxy = self.hassette._state_proxy
        return state_proxy.states.get(entity_id) if state_proxy else None

    @property
    def duration_timers_active(self) -> int:
        """Number of currently active duration timers."""
        return self._duration_timers_active

    async def _dispatch(self, topic: str, event: "Event[Any]", listener: "Listener") -> None:
        """Dispatch an event to a specific listener.

        All listeners go through ``_make_tracked_invoke_fn`` regardless of whether
        ``db_id`` is set.  When ``db_id`` is ``None`` (listener not yet registered),
        ``InvokeHandler`` is created with ``listener_id=None`` and the
        ``CommandExecutor`` records an orphan invocation row.

        Error contract:
            - ``_make_tracked_invoke_fn`` can propagate ``CancelledError`` — the
              ``CommandExecutor`` re-raises it after recording the cancellation.
            - The ``finally`` clause is safe because ``once + rate_limiting`` is
              prohibited by ``Listener.create()`` validation.  If that prohibition
              is ever relaxed, the ``finally`` must guard against ``CancelledError``
              to avoid removing a listener whose debounced handler hasn't fired yet.
            - For duration listeners the ``finally`` block skips ``once`` removal.
              Removal is delegated unconditionally to the DurationTimer callback
              after ``listener.dispatch()`` returns there.

        Concurrency model:
            Multiple spawned tasks may enter this method concurrently for the same
            listener (via ``task_bucket.spawn`` in ``dispatch``).  The once-guard
            (``_fired`` check-and-set) is owned by ``Listener.dispatch()`` — see its
            docstring for the atomicity argument.  The same single-threaded scheduling
            applies to the throttle check in ``RateLimiter._throttled_call``.
        """
        # FR4: invoke_fn captures the original triggering event.  Duration timer
        # callbacks re-verify current state via hold predicates but dispatch via
        # this invoke_fn — the handler receives the event that started the timer.
        invoke_fn = self._make_tracked_invoke_fn(topic, event, listener)

        if listener.once and listener.rate_limiter:
            raise RuntimeError("once + rate_limiting is prohibited; see Listener.create() validation")

        if listener.duration is not None and listener._duration_timer is not None:
            if listener.is_cancelled:
                return

            entity_id = listener.entity_id
            if not entity_id:
                self.logger.error(
                    "duration_fire: listener has no entity_id — construction invariant violated. "
                    "Listener owner=%s topic=%s",
                    listener.owner_id,
                    listener.topic,
                )
                return

            async def on_duration_fire() -> None:
                """Called by DurationTimer after the full hold period elapses."""
                try:
                    current_state = self._read_entity_state(entity_id)
                    if current_state is None:
                        self.logger.debug(
                            "duration_fire: entity %s not found in StateProxy, dropping fire",
                            entity_id,
                        )
                        return

                    recheck_event = self._make_synthetic_state_event(entity_id, current_state)

                    if not self._hold_matches(listener, recheck_event):
                        self.logger.debug(
                            "duration_fire: entity %s predicate no longer matches, dropping fire",
                            entity_id,
                        )
                        return

                    self.logger.debug(
                        "duration_fire: entity %s held state for %.2fs, dispatching handler",
                        entity_id,
                        listener.duration,
                    )
                    await listener.dispatch(invoke_fn)
                finally:
                    self._duration_timers_active -= 1
                    if listener.once:
                        self.remove_listener(listener)

            self._duration_timers_active += 1
            listener._duration_timer.start(on_duration_fire)
            return

        # Non-duration path (unchanged behavior).
        try:
            await listener.dispatch(invoke_fn)
        finally:
            if listener.once:
                self.remove_listener(listener)

    def _make_tracked_invoke_fn(
        self, topic: str, event: "Event[Any]", listener: "Listener"
    ) -> Callable[[], "Awaitable[None]"]:
        """Build an invoke function for all listeners with telemetry.

        The closure reads ``listener.db_id`` lazily at call time (not capture time)
        so that debounced handlers see the correct ``db_id`` after async registration
        completes.  When ``db_id`` is still ``None`` at fire time, ``InvokeHandler``
        is created with ``listener_id=None`` and produces an orphan record.

        Can propagate ``CancelledError`` — the ``CommandExecutor`` re-raises it after
        recording a cancellation record.
        """

        async def execute_fn() -> None:
            # Resolve effective timeout lazily at fire time (not capture time) so that
            # debounced handlers see config changes applied via hot reload, consistent
            # with the lazy db_id resolution documented above.
            if listener.timeout_disabled:
                effective_timeout = None
            elif listener.timeout is not None:
                effective_timeout = listener.timeout
            else:
                effective_timeout = self.hassette.config.event_handler_timeout_seconds

            cmd = InvokeHandler(
                listener=listener,
                event=event,
                topic=topic,
                listener_id=listener.db_id,
                source_tier=listener.source_tier,
                effective_timeout=effective_timeout,
            )
            await self._executor.execute(cmd)

        return execute_fn

    async def before_initialize(self) -> None:
        self.logger.debug("Waiting for Hassette ready event")
        await self.hassette.ready_event.wait()

    @property
    def is_dispatch_idle(self) -> bool:
        """Return True when no dispatch tasks are in flight.

        Delegates to ``_dispatch_idle_event.is_set()``. This is the recommended
        public accessor for drain helpers and test infrastructure — prefer this
        over reading ``_dispatch_idle_event`` directly.

        Returns:
            True if no handler dispatch tasks are currently running.
        """
        return self._dispatch_idle_event.is_set()

    @property
    def dispatch_pending_count(self) -> int:
        """Return the number of currently in-flight dispatch tasks.

        Delegates to ``_dispatch_pending``. This is the recommended public
        accessor for drain helpers and test infrastructure — prefer this over
        reading ``_dispatch_pending`` directly.

        Returns:
            The count of handler dispatch tasks currently running.
        """
        return self._dispatch_pending

    async def await_dispatch_idle(self, *, timeout: float = 2.0) -> None:
        """Wait until all dispatched handler tasks have completed.

        Uses a monotonic dispatch counter (incremented on spawn, decremented on
        task completion via ``_on_dispatch_done``) and an ``asyncio.Event`` that
        is set when the counter reaches zero.

        The method polls in a tight loop with short sleeps until the dispatch
        counter reaches zero and *stays* zero after a stability check. This
        handles the anyio memory channel pipeline: events may still be in
        transit between ``EventStreamService.send_event()`` and
        ``BusService.dispatch()`` when this method is first called. The
        stability check (idle event set after a yield) confirms no new
        dispatches were triggered by in-flight events.

        Note:
            This drains tasks spawned by ``BusService.dispatch()`` and
            ``_immediate_fire_task``.  Duration timer callbacks are NOT tracked
            here — they fire asynchronously via ``task_bucket.spawn()`` inside
            ``DurationTimer``.  Use ``duration_timers_active`` to check for
            pending duration fires.  Handler tasks that spawn secondary work
            via the app's own ``task_bucket`` are also not tracked here.

        Args:
            timeout: Maximum seconds to wait for dispatch tasks to complete.

        Raises:
            TimeoutError: If dispatch tasks are still running after ``timeout``.
        """
        deadline = asyncio.get_running_loop().time() + timeout

        while True:
            # Wait for in-flight dispatches to complete.
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(
                    f"BusService dispatch tasks did not complete within {timeout}s "
                    f"({self._dispatch_pending} dispatch tasks still pending)"
                )
            try:
                await asyncio.wait_for(self._dispatch_idle_event.wait(), timeout=remaining)
            except TimeoutError:
                raise TimeoutError(
                    f"BusService dispatch tasks did not complete within {timeout}s "
                    f"({self._dispatch_pending} dispatch tasks still pending)"
                ) from None

            # Stability check: yield to let any in-transit events from the
            # anyio memory channel reach serve() → dispatch(). If idle_event
            # is still set after the yield, no new dispatches were triggered
            # by in-flight events and we are truly idle.
            await asyncio.sleep(0.005)
            if self._dispatch_idle_event.is_set():
                break

    async def serve(self) -> None:
        """Worker loop that processes events from the stream."""

        async with self.stream:
            self.mark_ready(reason="Stream opened")
            async for event_name, event_data in self.stream:
                if self.shutdown_event.is_set():
                    if self._duration_timers_active > 0:
                        self.logger.info(
                            "Shutdown: %d active duration timer(s) will be cancelled",
                            self._duration_timers_active,
                        )
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

        Checks ``listener.is_cancelled`` before insertion to prevent orphaned
        listeners when ``Subscription.cancel()`` races with the async add task (#451).

        Args:
            topic: The topic to add the listener to.
            listener: The listener to add.
        """
        async with self.lock:
            if listener.is_cancelled:
                return
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
