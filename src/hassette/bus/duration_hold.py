"""Duration hold lifecycle manager for state-change listeners."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from hassette.bus.invocation import build_tracked_invoke_fn
from hassette.bus.listeners import DurationConfig, Listener, Subscription
from hassette.bus.router import Router
from hassette.events.base import Event
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
        make_synthetic_event: "Callable[[str, HassStateDict], Event[Any]]",
        compute_elapsed: "Callable[[HassStateDict, DurationConfig], float]",
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
        self._duration_timers_active: int = 0

    @property
    def duration_timers_active(self) -> int:
        """Number of currently active duration timers."""
        return self._duration_timers_active

    def decrement_timers_active(self) -> None:
        """Decrement the active timer counter on cancellation."""
        if self._duration_timers_active > 0:
            self._duration_timers_active -= 1

    def hold_matches(self, listener: Listener, event: Any) -> bool:
        """Check hold predicates (state-value only) against an event.

        Falls back to ``listener.matches()`` when no hold predicate is set.
        Catches predicate exceptions here because the duration-hold path has no
        executor access for telemetry recording — a raising predicate logs and
        returns False so the spawned timer task doesn't crash.
        """
        hold_pred = listener.duration_config.hold_predicate if listener.duration_config else None
        try:
            if hold_pred is None:
                return listener.matches(event)
            return hold_pred(event)
        except Exception:
            self.logger.exception("Predicate raised in hold_matches for %s; treating as non-match", listener)
            return False

    async def immediate_fire_task(self, listener: Listener) -> None:
        """Fire a handler immediately with the current entity state.

        Implements ``immediate=True``: fires once with a synthetic event built
        by the injected ``make_synthetic_event`` factory if the entity is in
        the cache.

        Error contract: any exception → log at WARNING; immediate fire becomes a no-op.
        ``state_reader`` handles state-read errors; the outer try/except catches
        everything else (synthetic event build, predicate match, dispatch).
        """
        duration_config = listener.duration_config
        entity_id = duration_config.entity_id if duration_config else None
        if not entity_id:
            self.logger.error(
                "immediate_fire: listener has no entity_id (invariant violated). owner=%s topic=%s",
                listener.identity.owner_id,
                listener.topic,
            )
            return

        current_state = self.state_reader(entity_id)
        if current_state is None:
            return

        try:
            synthetic_event = self.make_synthetic_event(entity_id, current_state)
            if not listener.matches(synthetic_event):
                return

            invoke_fn = build_tracked_invoke_fn(
                listener,
                synthetic_event,
                synthetic_event.topic,
                self.executor,
                self.config_resolver,
                is_synthetic=True,
            )

            if duration_config is not None and duration_config.duration is not None:
                elapsed = self.compute_elapsed(current_state, duration_config)
                if elapsed >= duration_config.duration:
                    try:
                        await listener.invoker.dispatch(invoke_fn)
                    finally:
                        if listener.options.once:
                            self.remove_listener(listener)
                else:
                    remaining = duration_config.duration - elapsed
                    self.logger.debug(
                        "immediate_fire: %s elapsed=%.2fs, timer remaining=%.2fs",
                        entity_id,
                        elapsed,
                        remaining,
                    )
                    self.start_remaining_duration_timer(
                        listener,
                        entity_id,
                        duration_config,
                        invoke_fn,
                        remaining,
                    )
                return

            try:
                await listener.invoker.dispatch(invoke_fn)
            finally:
                if listener.options.once:
                    self.remove_listener(listener)
        except Exception as exc:
            self.logger.warning(
                "immediate_fire: unexpected error for entity %s, immediate fire will not occur. owner=%s topic=%s",
                entity_id,
                listener.identity.owner_id,
                listener.topic,
                exc_info=exc,
            )

    def start_remaining_duration_timer(
        self,
        listener: Listener,
        entity_id: str,
        duration_config: DurationConfig,
        invoke_fn: "Callable[[], Awaitable[None]]",
        remaining: float,
    ) -> None:
        """Start a timer for the ``remaining`` hold seconds; rechecks predicates at fire time."""
        self._start_duration_timer(listener, entity_id, duration_config, invoke_fn, override_duration=remaining)

    def start_duration_timer(
        self,
        listener: Listener,
        entity_id: str,
        duration_config: DurationConfig,
        invoke_fn: "Callable[[], Awaitable[None]]",
    ) -> None:
        """Start the full-duration hold timer; rechecks predicates at fire time."""
        self._start_duration_timer(listener, entity_id, duration_config, invoke_fn)

    def _start_duration_timer(
        self,
        listener: Listener,
        entity_id: str,
        duration_config: DurationConfig,
        invoke_fn: "Callable[[], Awaitable[None]]",
        override_duration: float | None = None,
    ) -> None:
        async def on_duration_fire() -> None:
            try:
                current_state = self.state_reader(entity_id)
                if current_state is None:
                    self.logger.debug(
                        "duration_fire: entity %s not found in StateProxy, dropping fire",
                        entity_id,
                    )
                    return
                recheck_event = self.make_synthetic_event(entity_id, current_state)
                if not self.hold_matches(listener, recheck_event):
                    self.logger.debug(
                        "duration_fire: entity %s predicate no longer matches, dropping fire",
                        entity_id,
                    )
                    return
                await listener.invoker.dispatch(invoke_fn)
            finally:
                self.decrement_timers_active()
                if listener.options.once:
                    self.remove_listener(listener)

        self._duration_timers_active += 1
        if override_duration is not None:
            duration_config.timer.start(on_duration_fire, override_duration=override_duration)
        else:
            duration_config.timer.start(on_duration_fire)

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
        assert main_listener.duration_config is not None, "duration listener must have duration_config"
        duration_timer = main_listener.duration_config.timer
        entity_id = main_listener.duration_config.entity_id

        async def cancel_handler(event: Event[Any]) -> None:
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
