"""Duration hold lifecycle manager for state-change listeners."""

import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from hassette.bus.invocation import build_tracked_invoke_fn
from hassette.bus.listeners import EntityWatch, Listener, Subscription
from hassette.bus.router import Router
from hassette.events.base import AnyEvent
from hassette.types import Topic

if TYPE_CHECKING:
    import logging

    from hassette import TaskBucket
    from hassette.core.command_executor import CommandExecutor
    from hassette.events.hass.raw import HassStateDict


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
        self, listener: Listener, event: "AnyEvent", predicate: "Callable[[AnyEvent], bool]"
    ) -> bool | None:
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
            if not self.evaluate_predicate(listener, synthetic_event, listener.matches):
                return

            invoke_fn = build_tracked_invoke_fn(
                listener,
                synthetic_event,
                listener.topic,
                self.executor,
                self.config_resolver,
                is_synthetic=True,
            )

            if entity_watch.duration is not None:
                elapsed = self.compute_elapsed(current_state, entity_watch)
                if elapsed >= entity_watch.duration:
                    await self.dispatch_and_release_once(listener, synthetic_event, invoke_fn)
                else:
                    remaining = entity_watch.duration - elapsed
                    self.logger.debug(
                        "immediate_fire: %s elapsed=%.2fs, timer remaining=%.2fs",
                        entity_id,
                        elapsed,
                        remaining,
                    )
                    self.start_duration_timer(
                        listener,
                        entity_id,
                        entity_watch,
                        synthetic_event,
                        invoke_fn,
                        override_duration=remaining,
                        is_synthetic=True,
                    )
                return

            await self.dispatch_and_release_once(listener, synthetic_event, invoke_fn)
        except Exception as exc:
            self.logger.warning(
                "immediate_fire: unexpected error for entity %s, immediate fire will not occur. owner=%s topic=%s",
                entity_id,
                listener.identity.owner_id,
                listener.topic,
                exc_info=exc,
            )

    async def dispatch_and_release_once(
        self, listener: Listener, event: "AnyEvent", invoke_fn: "Callable[[], Awaitable[None]]"
    ) -> None:
        """Dispatch ``invoke_fn`` for ``event`` and remove a ``once`` listener afterwards, even if dispatch raises."""
        try:
            await listener.invoker.dispatch(event, invoke_fn, self.config_resolver)
        finally:
            if listener.options.once:
                self.remove_listener(listener)

    def start_duration_timer(
        self,
        listener: Listener,
        entity_id: str,
        entity_watch: EntityWatch,
        event: "AnyEvent",
        invoke_fn: "Callable[[], Awaitable[None]]",
        override_duration: float | None = None,
        *,
        is_synthetic: bool = False,
    ) -> None:
        """Start the hold timer for ``event``; rechecks predicates at fire time.

        ``override_duration`` sleeps for that many seconds instead of the full hold duration
        (the immediate-fire path passes the remaining hold time). ``is_synthetic`` says ``event`` was built from
        the cached state (the immediate-fire path).

        A failed recheck is a ``hold_recheck_failed`` near-miss. It records the event built from the state at fire
        time, or ``event`` itself when the entity is missing from the cache and there is no state to build one from.
        """

        async def on_duration_fire() -> None:
            report = listener.invoker.report_drop
            try:
                current_state = self.state_reader(entity_id)
                if current_state is None:
                    self.logger.debug(
                        "duration_fire: entity %s not found in StateProxy, dropping fire",
                        entity_id,
                    )
                    if report is not None:
                        report("hold_recheck_failed", event, is_synthetic=is_synthetic)
                    return
                recheck_event = self.make_synthetic_event(entity_id, current_state)
                matched = self.hold_matches(listener, recheck_event)
                if not matched:
                    self.logger.debug(
                        "duration_fire: entity %s predicate no longer matches, dropping fire",
                        entity_id,
                    )
                    # None means a hold predicate raised: that is recorded as an error run, not a miss.
                    if matched is False and report is not None:
                        report("hold_recheck_failed", recheck_event, is_synthetic=True)
                    return
                await listener.invoker.dispatch(event, invoke_fn, self.config_resolver)
            finally:
                self.decrement_timers_active()
                if listener.options.once:
                    self.remove_listener(listener)

        self._duration_timers_active += 1
        entity_watch.timer.start(on_duration_fire, override_duration=override_duration)

    def create_cancel_listener(self, main_listener: Listener) -> Subscription:
        """Create and register a cancellation listener for a duration timer.

        The cancellation listener monitors the same entity as ``main_listener``
        and calls ``DurationTimer.evaluate_cancel_event()`` on each incoming
        ``state_changed`` event.  The old_state stripping and predicate
        re-evaluation are handled inside ``evaluate_cancel_event()``.

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
            duration_timer.evaluate_cancel_event(event)

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
