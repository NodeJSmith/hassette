"""Duration timer for state-change listeners.

Manages a delayed fire with cancellation support.  The timer fires after the
entity has remained in a matching state for the configured duration.  A separate
cancellation subscription monitors the entity and cancels the timer if the state
leaves the matching condition.
"""

import asyncio
import typing
from logging import getLogger

if typing.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Any

    from hassette import TaskBucket
    from hassette.bus.listeners import Subscription
    from hassette.events.base import Event
    from hassette.types import Predicate

LOGGER = getLogger(__name__)


class DurationTimer:
    """Manages a single delayed-fire task with predicate-based cancellation.

    Follows the ``RateLimiter`` pattern: owns a single ``asyncio.Task``, provides
    ``start()`` / ``cancel()`` / ``is_active``, and is created once per ``Listener``
    in ``Listener.create()``.

    The cancellation subscription monitors the same entity and re-evaluates the
    main listener's predicates on each new event.  If the predicates no longer match
    (entity left the target state), the timer is cancelled.  If they still match,
    the timer continues — this prevents false cancellations from attribute-only
    refreshes.

    Attributes:
        task_bucket: TaskBucket for spawning background tasks.
        duration: Timer duration in seconds.
        predicates: Main listener predicates used to decide whether to cancel on a
            new event.
        entity_id: The entity this timer is tracking.
        owner_id: Owner identifier (same as the main listener's owner_id).
    """

    def __init__(
        self,
        task_bucket: "TaskBucket",
        duration: float,
        predicates: "Predicate | None",
        entity_id: str,
        owner_id: str,
        create_cancel_sub: "Callable[[], Subscription]",
    ) -> None:
        """Initialize the DurationTimer.

        Args:
            task_bucket: TaskBucket for spawning background tasks.
            duration: Timer duration in seconds.  Must be positive.
            predicates: Predicate from the main listener, used to decide whether to
                cancel when a new event arrives for the entity.
            entity_id: The entity ID being monitored.
            owner_id: Owner identifier from the main listener.
            create_cancel_sub: Factory callback that creates (and registers) the
                cancellation subscription.  Called in ``start()`` whenever the
                existing sub has been consumed or is None.  In unit tests, pass a
                mock that returns a ``MagicMock()`` acting as a ``Subscription``.
        """
        self.task_bucket = task_bucket
        self.duration = duration
        self.predicates = predicates
        self.entity_id = entity_id
        self.owner_id = owner_id
        self._create_cancel_sub = create_cancel_sub

        self._task: asyncio.Task[None] | None = None
        self._cancel_sub: Subscription | None = None
        self._cancelled = False

    @property
    def is_active(self) -> bool:
        """True when a timer task is pending (started but not yet fired or cancelled)."""
        return self._task is not None and not self._task.done()

    def start(
        self,
        triggering_event: "Event[Any]",
        on_fire: "Callable[[], Awaitable[None]]",
    ) -> None:
        """Start (or restart) the duration timer.

        If a previous task is running it is cancelled first.  A fresh cancellation
        subscription is created if the current one has been consumed or is None,
        ensuring each timer cycle has an active cancellation path.

        Clears ``_cancelled`` so that a previously-cancelled timer can be restarted
        when the entity re-enters the target state.  The flag is only set transiently
        during a cancel cycle to guard an in-flight ``delayed_fire`` coroutine; once
        ``start()`` is called again, the new task replaces the old cycle entirely.

        Args:
            triggering_event: The event that triggered this timer start (passed to
                the cancellation handler if it fires before the timer elapses).
            on_fire: Async zero-arg callable invoked when the timer elapses.
        """
        # Clear the cancelled guard so this new cycle runs normally.
        # The guard's purpose is to prevent an in-flight delayed_fire from firing
        # after cancel(); once we start a fresh cycle, that concern no longer applies.
        self._cancelled = False

        # Cancel previous task if still running.
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None

        # Re-create the cancellation subscription if it has been consumed or is absent.
        if self._cancel_sub is None:
            self._cancel_sub = self._create_cancel_sub()

        async def delayed_fire() -> None:
            try:
                await asyncio.sleep(self.duration)
            except asyncio.CancelledError:
                # Cancellation is expected — either start() replaced us or cancel() ran.
                return
            # Guard: if the timer was cancelled while sleeping, do not fire.
            if self._cancelled:
                return
            # Clear the task reference before firing — is_active returns False from here.
            self._task = None
            # Cancel the cancellation subscription — entity is now in confirmed state.
            if self._cancel_sub is not None:
                self._cancel_sub.cancel()
                self._cancel_sub = None
            await on_fire()

        self._task = self.task_bucket.spawn(delayed_fire(), name="bus:duration_timer")

    def cancel(self) -> None:
        """Cancel any pending timer task and the cancellation subscription.

        Idempotent — safe to call multiple times.  The ``_cancelled`` flag is set
        first (mirroring ``RateLimiter.cancel()``) so that any in-flight
        ``delayed_fire`` coroutine sees it and skips the ``on_fire`` callback.

        The cancellation subscription is removed synchronously (no
        ``task_bucket.spawn()``) to avoid shutdown-ordering dependencies.

        Terminal operation — the DurationTimer must not be reused after this call.
        """
        self._cancelled = True  # idempotency guard — MUST be first

        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

        if self._cancel_sub is not None:
            self._cancel_sub.cancel()
            self._cancel_sub = None

    def _on_cancel_event(self, event: "Event[Any]") -> None:
        """Handle an entity state-change event from the cancellation subscription.

        Re-evaluates the main listener's predicates against the new event.  If the
        predicates no longer match, the entity has left the target state and the
        timer is cancelled.  If they still match, the entity remains in the target
        state and the timer continues.

        Args:
            event: The new state-change event for the monitored entity.
        """
        if self._cancelled:
            return

        if self.predicates is not None and not self.predicates(event):
            # Entity left the target state — cancel the timer.
            LOGGER.debug(
                "DurationTimer: predicates no longer match for entity=%s, cancelling timer",
                self.entity_id,
            )
            self.cancel()
        # else: entity is still in target state — timer continues
