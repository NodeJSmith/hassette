"""Duration hold lifecycle manager for state-change listeners."""

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from hassette.bus.delivery import Delivery
from hassette.bus.listeners import MATCHED, EntityWatch, Listener, Subscription
from hassette.bus.router import Router
from hassette.events.base import AnyEvent
from hassette.types import Topic

if TYPE_CHECKING:
    import logging

    from hassette import TaskBucket
    from hassette.core.command_executor import CommandExecutor
    from hassette.events.hass.raw import HassStateDict


_R = TypeVar("_R")
"""``evaluate_predicate``'s predicate result: ``bool`` for ``matches`` and hold predicates, ``int`` for ``evaluate``."""


class DurationHoldManager:
    """Manages duration hold lifecycle for bus listeners.

    Handles immediate fire, full/remaining timer start, cancel listener
    creation, and hold predicate matching. Dependencies are injected
    via constructor parameters — no reference to BusService.
    """

    def __init__(
        self,
        executor: "CommandExecutor",
        config_resolver: Callable[[], float | None],
        state_reader: Callable[[str], "HassStateDict | None"],
        remove_listener: Callable[[Listener], None],
        router: Router,
        task_bucket: "TaskBucket",
        logger: "logging.Logger",
        make_synthetic_event: "Callable[[str, HassStateDict], AnyEvent]",
        compute_elapsed: "Callable[[HassStateDict, EntityWatch], float]",
        record_predicate_failure: "Callable[[Listener, str, AnyEvent, Exception, float], None]",
    ) -> None:
        """Initialize the DurationHoldManager.

        Args:
            executor: CommandExecutor that records telemetry and runs handlers.
            config_resolver: Callable that returns current event_handler_timeout_seconds,
                or None if no global timeout is configured. Called lazily at fire time.
            state_reader: Callable that reads entity state from StateProxy by entity_id.
                Returns None if entity not found or StateProxy is unavailable.
                All error handling (ResourceNotReadyError, etc.) is absorbed by the caller.
            remove_listener: Idempotent callable that removes a listener from the router.
            router: Router for synchronous cancel-listener route insertion.
            task_bucket: TaskBucket for spawning background tasks.
            logger: Logger for structured logging.
            make_synthetic_event: Builds a synthetic state-change event with old_state=None
                from an entity_id and its current state dict. Injected from core so the bus
                kernel does not import HA event types.
            compute_elapsed: Computes how long an entity has been in its current state,
                reading HA-specific fields from the state dict. Injected from core so the
                bus kernel does not import HA event types.
            record_predicate_failure: Records a raising predicate as a failed execution and
                routes it to the listener's (or app-level) error handler. Takes
                ``(listener, topic, event, exc, start_ts)`` and must not raise. Every event it receives
                was built by ``make_synthetic_event``, so it records the row as synthetic. Injected from
                ``BusService`` so the duration-hold paths share the main dispatch path's
                failure handling.
        """
        self.executor = executor
        self.config_resolver = config_resolver
        self.state_reader = state_reader
        self.remove_listener = remove_listener
        self.router = router
        self.task_bucket = task_bucket
        self.logger = logger
        self.make_synthetic_event = make_synthetic_event
        self.compute_elapsed = compute_elapsed
        self.record_predicate_failure = record_predicate_failure
        self._duration_timers_active: int = 0

    @property
    def duration_timers_active(self) -> int:
        """Number of currently active duration timers."""
        return self._duration_timers_active

    def decrement_timers_active(self) -> None:
        """Decrement the active timer counter when a timer cycle ends (fired or cancelled)."""
        if self._duration_timers_active > 0:
            self._duration_timers_active -= 1

    def hold_matches(self, listener: Listener, event: "AnyEvent") -> bool | None:
        """Check hold predicates (state-value only) against an event.

        Falls back to ``listener.matches()`` when no hold predicate is set.
        A raising predicate is recorded via ``record_predicate_failure`` (error
        ``ExecutionRecord`` + error-handler routing, same as the main dispatch path)
        and returns None, a non-match that isn't a near-miss, so the spawned timer task doesn't crash.
        """
        hold_pred = listener.entity_watch.hold_predicate if listener.entity_watch else None
        return self.evaluate_predicate(listener, event, hold_pred if hold_pred is not None else listener.matches)

    def evaluate_predicate(
        self, listener: Listener, event: "AnyEvent", predicate: "Callable[[AnyEvent], _R]"
    ) -> _R | None:
        """Run ``predicate`` against ``event``; a raise is recorded and returns None, a non-match."""
        predicate_start = time.time()
        try:
            return predicate(event)
        except Exception as exc:
            self.logger.exception("Predicate raised for %s; treating as non-match", listener)
            self.record_predicate_failure(listener, listener.topic, event, exc, predicate_start)
            return None

    async def immediate_fire_task(self, listener: Listener, entity_watch: EntityWatch) -> None:
        """Fire a handler immediately with the current entity state.

        Implements ``immediate=True``: fires once with a synthetic event built
        by the injected ``make_synthetic_event`` factory if the entity is in
        the cache.

        Error contract: any exception → log at WARNING; immediate fire becomes a no-op.
        ``state_reader`` handles state-read errors; the outer try/except catches
        everything else (synthetic event build, timer setup, dispatch). A raising
        predicate is additionally recorded via ``record_predicate_failure`` (error
        ``ExecutionRecord`` + error-handler routing); other failures are log-only, since
        they are not predicate failures and a synthetic-event build failure leaves no
        event to hand an error handler.
        """
        entity_id = entity_watch.entity_id
        current_state = self.state_reader(entity_id)
        if current_state is None:
            return

        try:
            synthetic_event = self.make_synthetic_event(entity_id, current_state)
            delivery = Delivery(listener, synthetic_event, listener.topic, is_synthetic=True)
            result = self.evaluate_predicate(listener, synthetic_event, listener.evaluate)
            if result is None:
                return
            if result != MATCHED:
                # Synthetic events skip BusService._match_listeners, so the filter near-miss is reported here.
                delivery.drop_if_filtered(result)
                return

            if entity_watch.duration is not None:
                elapsed = self.compute_elapsed(current_state, entity_watch)
                if elapsed >= entity_watch.duration:
                    await self.dispatch_and_release_once(delivery)
                else:
                    remaining = entity_watch.duration - elapsed
                    self.logger.debug(
                        "immediate_fire: %s elapsed=%.2fs, timer remaining=%.2fs",
                        entity_id,
                        elapsed,
                        remaining,
                    )
                    self.start_duration_timer(delivery, override_duration=remaining)
                return

            await self.dispatch_and_release_once(delivery)
        except Exception as exc:
            self.logger.warning(
                "immediate_fire: unexpected error for entity %s, immediate fire will not occur. owner=%s topic=%s",
                entity_id,
                listener.identity.owner_id,
                listener.topic,
                exc_info=exc,
            )

    async def dispatch_and_release_once(self, delivery: Delivery) -> None:
        """Dispatch ``delivery`` and remove a ``once`` listener afterwards, even if dispatch raises."""
        listener = delivery.listener
        try:
            await listener.invoker.dispatch(delivery, self.executor, self.config_resolver)
        finally:
            if listener.options.once:
                self.remove_listener(listener)

    def start_duration_timer(self, delivery: Delivery, override_duration: float | None = None) -> None:
        """Start the hold timer for ``delivery``, a duration listener's; rechecks predicates at fire time.

        ``override_duration`` sleeps for that many seconds instead of the full hold duration
        (the immediate-fire path passes the remaining hold time). A hold that survives the recheck dispatches
        ``delivery`` itself, so the handler receives the event that started the hold.

        A failed recheck is a ``hold_recheck_failed`` near-miss that records the event built from the state at fire
        time, as synthetic. An entity missing from the cache is a ``hold_entity_missing`` near-miss that records
        ``delivery`` itself, since there is no state to build one from.
        """
        listener = delivery.listener
        entity_watch = listener.entity_watch
        if entity_watch is None:  # only narrows the type: callers pass a delivery for a listener with a watch
            raise RuntimeError("start_duration_timer requires a listener with an entity_watch")
        entity_id = entity_watch.entity_id

        async def on_duration_fire() -> None:
            try:
                current_state = self.state_reader(entity_id)
                if current_state is None:
                    self.logger.debug(
                        "duration_fire: entity %s not found in StateProxy, dropping fire",
                        entity_id,
                    )
                    delivery.drop("hold_entity_missing")
                    return
                recheck_event = self.make_synthetic_event(entity_id, current_state)
                matched = self.hold_matches(listener, recheck_event)
                if not matched:
                    self.logger.debug(
                        "duration_fire: entity %s predicate no longer matches, dropping fire",
                        entity_id,
                    )
                    # None means a hold predicate raised: that is recorded as an error run, not a miss.
                    # The recheck event is rebuilt from the cached state, so it is synthetic whatever started the hold.
                    if matched is False:
                        Delivery(listener, recheck_event, listener.topic, is_synthetic=True).drop("hold_recheck_failed")
                    return
                await listener.invoker.dispatch(delivery, self.executor, self.config_resolver)
            finally:
                self.decrement_timers_active()
                if listener.options.once:
                    self.remove_listener(listener)

        self._duration_timers_active += 1
        entity_watch.timer.start(on_duration_fire, override_duration=override_duration)

    def create_cancel_listener(self, main_listener: Listener) -> Subscription:
        """Create and register a cancellation listener for a duration timer.

        The cancellation listener monitors the same entity as ``main_listener``
        and calls ``DurationTimer.cancel_if_left_state()`` on each incoming
        ``state_changed`` event.  The old_state stripping and predicate
        re-evaluation are handled inside ``cancel_if_left_state()``. An event
        that ends an active hold is reported as a ``hold_cancelled`` near-miss
        of ``main_listener``, carrying the event as received (with its old_state).

        Route insertion is synchronous — the cancel-listener is immediately
        routable when this method returns. No background task is spawned for
        route insertion; ``_dispatch_pending`` is not incremented.

        Properties:
        - Uses ``source_tier="framework"`` (filtered from user-facing counts).
        - Uses the same ``owner_id`` as the main listener (cleaned up together).
        - Bypasses DB registration (no ``ListenerRegistration`` row).

        Args:
            main_listener: The duration listener whose timer this subscription guards.

        Returns:
            A ``Subscription`` whose ``cancel()`` removes the listener from Router.
        """
        if main_listener.entity_watch is None:
            raise RuntimeError("duration listener must have entity_watch")
        duration_timer = main_listener.entity_watch.timer
        entity_id = main_listener.entity_watch.entity_id

        async def cancel_handler(event: AnyEvent) -> None:
            if duration_timer.cancel_if_left_state(event):
                Delivery(main_listener, event, main_listener.topic).drop("hold_cancelled")

        cancel_listener = Listener.create_cancel_listener(
            task_bucket=self.task_bucket,
            owner_id=main_listener.identity.owner_id,
            topic=f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{entity_id}",
            handler=cancel_handler,
        )

        # Sync route insertion — no task spawn, no _dispatch_pending tracking.
        self.router.add_route(cancel_listener.topic, cancel_listener)

        def unsubscribe() -> None:
            cancel_listener.cancel()
            self.router.remove_listener_by_id(cancel_listener.topic, cancel_listener.listener_id)

        return Subscription(cancel_listener, unsubscribe)
