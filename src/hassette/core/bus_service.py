import asyncio
import time
import typing
from collections import defaultdict
from typing import Any, ClassVar, NamedTuple

from hassette.bus.duration_hold import DurationHoldManager
from hassette.bus.invocation import build_tracked_invoke_fn
from hassette.bus.listeners import Listener, Subscription
from hassette.bus.router import Router
from hassette.core.database_service import DatabaseService
from hassette.core.event_filter import EventFilter
from hassette.core.registration import ListenerRegistration
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.event_handling.predicates import summarize_top_level
from hassette.events import Event, HassPayload
from hassette.exceptions import ResourceNotReadyError
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.types.enums import BackpressurePolicy, RestartType
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

# Rate-limit window for the "dispatch saturated" warning so a sustained flood logs once
# per window, not once per blocked dispatch. Mirrors sync_executor_service saturation warns.
_DISPATCH_SATURATION_WARN_RATE_LIMIT_SECS = 30.0

_HASS_TOPIC_PREFIX = "hass."
_HASSETTE_TOPIC_PREFIX = "hassette."


class LiveCounts(NamedTuple):
    """Live execution count snapshot for a single listener.

    All three counters are in-memory only and reset on restart.
    """

    suppressed: int
    """Events dropped by the single-mode guard while a prior invocation was running."""

    dropped: int
    """Events dropped by the queued-mode guard when the queue cap was reached."""

    backpressure_dropped: int
    """Events dropped at the dispatch acquire gate due to DROP_NEWEST backpressure."""


class BusService(Service):
    """EventBus service that handles event dispatching and listener management."""

    depends_on: ClassVar[list[type["Resource"]]] = [DatabaseService, SyncExecutorService]
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.PERMANENT,
        budget_intensity=2,
        budget_period_seconds=30,
    )

    stream: "MemoryObjectReceiveStream[Event[Any]]"
    """Stream to receive events from."""

    router: "Router"
    """Router to manage event listeners."""

    _removal_callbacks: "dict[str, Callable[[Listener], None]]"
    """Per-owner callbacks invoked when a listener is removed (via remove_listener or
    remove_listeners_by_owner)."""

    def __init__(
        self,
        hassette: "Hassette",
        *,
        stream: "MemoryObjectReceiveStream[Event[Any]]",
        executor: "CommandExecutor",
        parent: "Resource | None" = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        self.stream = stream
        self._executor = executor
        self.router = Router()
        # Dispatch tracking for deterministic drain in test harnesses.
        self._dispatch_pending: int = 0
        self._dispatch_idle_event: asyncio.Event = asyncio.Event()
        self._dispatch_idle_event.set()  # starts idle

        # Bound concurrent handler invocations so a fan-out flood can't spawn unbounded tasks.
        # Read once at startup — resizing requires a restart (see LifecycleConfig docstring).
        self._dispatch_semaphore: asyncio.Semaphore = asyncio.Semaphore(
            hassette.config.lifecycle.max_concurrent_dispatches
        )
        self._last_saturation_warn_ts: float = 0.0

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
            state_reader=self.read_entity_state,
            remove_listener=self.remove_listener,
            router=self.router,
            task_bucket=self.task_bucket,
            logger=self.logger,
        )

        self._removal_callbacks = {}

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.bus_service

    @property
    def config_log_all_events(self) -> bool:
        """Return whether to log all events.

        Live read (not cached) so config hot-reload is honored at dispatch time, the same
        way the sibling ``config_log_level`` property re-reads config on every access. Do
        not change this back to ``@cached_property`` — it would freeze the value after the
        first dispatch and silently ignore hot-reload.
        """
        return self.hassette.config.logging.all_events

    def on_dispatch_done(self, _task: asyncio.Task[Any]) -> None:
        """Callback for dispatch task completion — decrements pending counter."""
        if self._dispatch_pending <= 0:
            self.logger.warning("_dispatch_pending underflow detected (was %d); resetting to 0", self._dispatch_pending)
            self._dispatch_pending = 0
            self._dispatch_idle_event.set()
            return
        self.decrement_dispatch_pending()

    def decrement_dispatch_pending(self) -> None:
        """Decrement the pending-dispatch counter and signal idle when it reaches zero."""
        self._dispatch_pending -= 1
        if self._dispatch_pending == 0:
            self._dispatch_idle_event.set()

    def release_dispatch_slot(self, _task: asyncio.Task[Any]) -> None:
        """Release one dispatch slot when a fan-out task finishes (success, error, or cancel).

        Attached only to fan-out tasks, which each acquire exactly one slot. The immediate-fire
        path in ``add_listener`` spawns without acquiring, so it must not get this callback.
        """
        self._dispatch_semaphore.release()

    def warn_dispatch_saturated(self) -> None:
        """Log a rate-limited warning when dispatch is at its concurrency ceiling."""
        now = time.monotonic()
        if now - self._last_saturation_warn_ts < _DISPATCH_SATURATION_WARN_RATE_LIMIT_SECS:
            return
        self._last_saturation_warn_ts = now
        self.logger.warning(
            "Event dispatch saturated: %d concurrent handlers in flight (max_concurrent_dispatches). "
            "Listeners may wait for a slot or drop events per their backpressure policy; "
            "sustained saturation backpressures HA event intake. "
            "Raise lifecycle.max_concurrent_dispatches or speed up slow handlers.",
            self.hassette.config.lifecycle.max_concurrent_dispatches,
        )

    async def add_listener(self, listener: "Listener") -> int:
        """Add a listener to the bus.

        Route insertion is synchronous. DB registration is awaited inline before
        returning — the listener's db_id is set and valid on return. For duration
        listeners, wires the timer and delegates cancel listener creation to
        ``DurationHoldManager``. Immediate-fire tasks are tracked in
        ``_dispatch_pending`` so ``await_dispatch_idle`` drains them.

        Returns:
            The db_id assigned to the listener by the database.
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

        # Await DB registration inline — db_id is set before route insertion.
        reg = self.build_registration(listener)
        db_id = await self._executor.register_listener(reg)
        listener.mark_registered(db_id)

        # Sync: insert route — listener is routable after DB registration.
        self.router.add_route(listener.topic, listener)

        if listener.duration_config is not None and listener.duration_config.immediate:
            self._dispatch_pending += 1
            self._dispatch_idle_event.clear()
            immediate_task = self.task_bucket.spawn(
                self._duration_hold.immediate_fire_task(listener),
                name="bus:immediate_fire",
            )
            immediate_task.add_done_callback(self.on_dispatch_done)

        return db_id

    def build_registration(self, listener: Listener) -> ListenerRegistration:
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
            mode=listener.options.mode.value,
            backpressure=listener.options.backpressure.value,
        )

    def live_execution_counts(self) -> "dict[int, LiveCounts]":
        """Return a snapshot of live execution counts keyed by listener ``db_id``.

        Reads each active listener's ``ExecutionModeGuard`` and ``HandlerInvoker`` from the
        router. Live and in-memory only — no DB access. Listeners not yet assigned a ``db_id``
        are skipped; the web layer treats a missing entry as ``LiveCounts(0, 0, 0)``. The
        counters reset on guard restart and are never persisted.

        Returns:
            A dict mapping listener ``db_id`` to a :class:`LiveCounts` NamedTuple.
        """
        # No awaits in this method — safe from asyncio mutation races against add_listener /
        # remove_listener (router.owners is only mutated on the event loop). Do not add an await
        # to this loop without adding synchronization, or the snapshot could tear.
        counts: dict[int, LiveCounts] = {}
        for listeners in self.router.owners.values():
            for listener in listeners:
                if listener.db_id is None:
                    continue
                guard = listener.invoker.guard
                counts[listener.db_id] = LiveCounts(
                    suppressed=guard.suppressed,
                    dropped=guard.dropped,
                    backpressure_dropped=listener.invoker.backpressure_dropped,
                )
        return counts

    async def mark_listener_cancelled(self, db_id: int) -> None:
        """Persist durable cancellation state for a listener by setting ``cancelled_at`` in the DB.

        Delegates to ``CommandExecutor.mark_listener_cancelled``. Called from the bus cancel
        path (``Subscription.cancel`` → ``Bus.remove_listener``, ``replace``'s cancel-old
        step, or a once-listener firing) so that a replaced or cancelled listener's removal
        is observable in telemetry, mirroring ``SchedulerService.mark_job_cancelled``.

        Args:
            db_id: The ``id`` of the ``listeners`` row to mark as cancelled.
        """
        await self._executor.mark_listener_cancelled(db_id)

    def register_removal_callback(self, owner_id: str, callback: "Callable[[Listener], None]") -> None:
        """Register a callback invoked whenever a listener belonging to owner_id is removed.

        If a callback is already registered for owner_id, the new one silently replaces it.
        This handles hot-reload cycles where the old Bus is orphaned without a formal shutdown.

        Args:
            owner_id: The owner whose listener removals should trigger the callback.
            callback: Called with the removed Listener as its single argument.
        """
        self._removal_callbacks[owner_id] = callback

    def deregister_removal_callback(self, owner_id: str) -> None:
        """Remove the removal callback for owner_id, if any.

        No-op when owner_id has no registered callback. Called by Bus.on_shutdown so
        the slot is freed before the Bus is re-initialized (e.g. during a hot-reload cycle).

        Args:
            owner_id: The owner whose callback should be removed.
        """
        self._removal_callbacks.pop(owner_id, None)

    def remove_listener(self, listener: "Listener") -> None:
        """Synchronously cancel and remove a listener from the routing table.

        Fires the per-owner removal callback (if registered) after removal. This closes the
        once-fire gap: the dispatch finally block calls this method directly, bypassing
        Bus.remove_listener, so the callback is the only way to notify the Bus that the
        once-listener's natural key should be released from _registered_listeners.
        """
        listener.cancel()
        self.router.remove_listener_by_id(listener.topic, listener.listener_id)
        self.fire_removal_callback(listener)

    def remove_listeners_by_owner(self, owner: str) -> None:
        """Remove all listeners owned by a specific owner synchronously.

        Fires the per-owner removal callback for each removed listener, mirroring
        SchedulerService._remove_jobs_by_owner. On the shutdown path Bus.remove_all_listeners
        pre-clears _registered_listeners first, so the callbacks find nothing to pop and skip
        the cancelled_at spawn; firing them here keeps this method correct for any future caller
        that removes listeners without that pre-clear.
        """
        removed = self.router.clear_owner(owner)
        for listener in removed:
            listener.cancel()
            self.fire_removal_callback(listener)

    def fire_removal_callback(self, listener: "Listener") -> None:
        """Invoke the per-owner removal callback for listener, if one is registered.

        Singular (one listener per call) by design: the bus fires on each removal as it
        happens, where SchedulerService.fire_removal_callbacks batches a list at the end
        of a bulk operation.
        """
        callback = self._removal_callbacks.get(listener.identity.owner_id)
        if callback is not None:
            callback(listener)

    def get_listeners_by_owner(self, owner: str) -> list["Listener"]:
        """Get all listeners owned by a specific owner."""
        return self.router.get_listeners_by_owner(owner)

    def should_log_event(self, event: "Event[Any]") -> bool:
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

        if self.should_log_event(event):
            self.logger.debug("Event: %r", event)

        routes = self.expand_topics(base_topic, event)  # ordered: most specific -> least
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
                # Acquire a slot before spawning so the fan-out can't outrun handler capacity.
                # A blocked acquire stalls the dispatch loop -> serve loop -> inbound channel,
                # propagating backpressure to the WS reader. locked() exactly predicts a blocking
                # acquire here: no await separates the two, so no other task changes the count between.
                if self._dispatch_semaphore.locked():
                    # Keep this call before the `await acquire()` below: the BLOCK-path test
                    # `test_block_listener_blocks_then_runs_under_saturation` hooks
                    # `warn_dispatch_saturated` as a deterministic signal that dispatch has reached
                    # the block. Moving it after the acquire would make that test pass vacuously.
                    self.warn_dispatch_saturated()
                    if listener.options.backpressure is BackpressurePolicy.DROP_NEWEST:
                        # Single writer: this loop, on the event loop, NO await between locked() and
                        # the increment — the same no-await window that makes the saturation check
                        # race-free. Do not insert an await (e.g. metrics emit) between them.
                        listener.invoker.backpressure_dropped += 1
                        self.logger.debug(
                            "backpressure drop_newest: skipping event for %s",
                            listener.identity.name or listener.identity.handler_short_name,
                        )
                        continue  # no acquire, no spawn, no pending/idle bookkeeping
                await self._dispatch_semaphore.acquire()

                self._dispatch_pending += 1
                self._dispatch_idle_event.clear()
                try:
                    task = self.task_bucket.spawn(self._dispatch(route, event, listener), name="bus:dispatch_listener")
                except BaseException:
                    # Spawn failed: no task runs, so no done-callback fires. Release the slot and
                    # unwind the pending bookkeeping by hand.
                    self._dispatch_semaphore.release()
                    self.decrement_dispatch_pending()
                    raise
                # Release the slot before decrementing pending so a newly-unblocked waiter sees
                # a consistent state (slot free, pending still counts the completing task).
                task.add_done_callback(self.release_dispatch_slot)
                task.add_done_callback(self.on_dispatch_done)

    def expand_topics(self, topic: str, event: Event[Any]) -> list[str]:
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

    def read_entity_state(self, entity_id: str) -> "HassStateDict | None":
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
            async for event in self.stream:
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
                    await self.dispatch(str(event.topic), event)
                except Exception as e:
                    self.logger.exception("Error processing event: %s", e)
