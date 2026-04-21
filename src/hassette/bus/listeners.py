import itertools
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from logging import Logger, getLogger
from typing import Any, cast

from hassette.bus.injection import ParameterInjector
from hassette.bus.rate_limiter import RateLimiter
from hassette.event_handling.predicates import normalize_where
from hassette.types.types import SourceTier
from hassette.utils.func_utils import callable_name
from hassette.utils.type_utils import get_typed_signature

if typing.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from hassette import TaskBucket
    from hassette.bus.duration_timer import DurationTimer
    from hassette.events.base import Event
    from hassette.types import AsyncHandlerType, HandlerType, Predicate

LOGGER = getLogger(__name__)

# next_id() is only called at listener creation time on the event loop thread.
# itertools.count.__next__ is C-atomic. No lock needed unless the project targets
# free-threaded CPython (PEP 703), which would require a broader concurrency audit.
seq = itertools.count(1)


def next_id() -> int:
    return next(seq)


@dataclass(slots=True)
class Listener:
    """A listener for events with a specific topic and handler."""

    logger: Logger
    """Logger for the listener."""

    listener_id: int = field(default_factory=next_id, init=False)
    """Unique identifier for the listener instance."""

    owner_id: str
    """Unique string identifier for the owner of the listener, e.g., a component or integration name."""

    topic: str
    """Topic the listener is subscribed to."""

    orig_handler: "HandlerType"
    """Original handler function provided by the user."""

    _async_handler: "AsyncHandlerType"
    """Async-wrapped handler function. Private — not part of the public API."""

    _injector: ParameterInjector
    """Parameter injector for dependency injection. Private — invoked by :meth:`invoke`."""

    predicate: "Predicate | None"
    """Predicate to filter events before invoking the handler."""

    app_key: str = ""
    """Configuration-level app key for DB registration (e.g., 'my_app'). Empty for non-App owners."""

    instance_index: int = 0
    """App instance index for DB registration. 0 for non-App owners."""

    kwargs: Mapping[str, Any] | None = None
    """Keyword arguments to pass to the handler."""

    once: bool = False
    """Whether the listener should be removed after one invocation."""

    debounce: float | None = None
    """Debounce delay in seconds. Events reset the timer; handler fires after the quiet period."""

    throttle: float | None = None
    """Throttle interval in seconds. At most one handler execution per window; extras are dropped."""

    timeout: float | None = None
    """Per-listener timeout in seconds. Overrides the global event_handler_timeout_seconds config.
    None means fall through to the config default."""

    timeout_disabled: bool = False
    """When True, disables timeout enforcement for this listener regardless of config."""

    priority: int = 0
    """Priority for listener ordering. Higher values run first. Default is 0 for app handlers."""

    db_id: int | None = None
    """Database row ID for this listener. Set by the executor after persistence; None until then."""

    _rate_limiter: RateLimiter | None = field(default=None, init=False, repr=False)
    """Rate limiter for debounce/throttle. Private — use :attr:`rate_limiter` for read access
    and :meth:`cancel` for lifecycle management.  Contains an active runtime component
    (spawns tasks, holds event loop references) — not a simple scalar like ``_fired``."""

    _duration_timer: "DurationTimer | None" = field(default=None, init=False, repr=False)
    """Duration timer for state-hold listeners. Private — constructed in :meth:`create` when
    ``duration`` is set, and cancelled in :meth:`cancel` alongside ``_rate_limiter``."""

    handler_name: str = ""
    """Human-readable name for the handler, computed once at creation time."""

    handler_short_name: str = ""
    """Short (last-segment) name for the handler, computed once at creation time."""

    source_location: str = ""
    """Captured source location (file:line) of the user code that registered this listener."""

    registration_source: str = ""
    """Captured source code snippet of the registration call."""

    name: str | None = None
    """Optional stable name for the listener (the name= escape hatch on Bus.on())."""

    source_tier: SourceTier = "app"
    """Whether this listener originates from a user app or the framework itself."""

    immediate: bool = False
    """If True, fire the handler immediately with the current entity state on registration."""

    duration: float | None = None
    """Duration in seconds the entity must remain in the matching state before the handler fires."""

    entity_id: str | None = None
    """Entity ID for this listener. Set by on_state_change/on_attribute_change at registration time."""

    hold_predicate: "Predicate | None" = None
    """State-value predicates only (excludes transition predicates like StateFrom, StateDidChange).
    Used by DurationTimer for cancel evaluation and fire-time recheck.  None when duration is not set."""

    is_attribute_listener: bool = False
    """True when this listener was registered via on_attribute_change.

    Used by the immediate+duration elapsed-time path: attribute listeners always start
    from zero elapsed time because HA's last_changed reflects primary state changes, not
    attribute changes.  See the design doc for the documented known limitation.
    """

    _cancelled: bool = field(default=False, init=False, repr=False)
    """Set by cancel() to signal that a pending add_listener task should skip route insertion.
    Prevents orphaned listeners when Subscription.cancel() races with the async add task (#451)."""

    _fired: bool = field(default=False, init=False, repr=False)
    """Guard for once=True listeners: set before the first invocation to prevent double-fire
    when two rapid events both match before the removal task executes."""

    @property
    def is_cancelled(self) -> bool:
        """Whether this listener has been cancelled. Read-only — use :meth:`cancel` to set."""
        return self._cancelled

    @property
    def rate_limiter(self) -> RateLimiter | None:
        """Read-only access to the rate limiter. Use :meth:`cancel` for lifecycle management."""
        return self._rate_limiter

    def mark_registered(self, db_id: int) -> None:
        """Set the database ID after persistence. One-time assignment by BusService."""
        if self.db_id is not None:
            LOGGER.warning(
                "Listener %s already registered with db_id=%s, ignoring new db_id=%s",
                self.listener_id,
                self.db_id,
                db_id,
            )
            return
        self.db_id = db_id

    def mark_fired(self) -> None:
        """Mark this once-listener as having fired. Called internally by dispatch()."""
        self._fired = True

    async def dispatch(self, invoke_fn: "Callable[[], Awaitable[None]]") -> None:
        """Apply rate limiting around the given invoke function.

        BusService builds the invoke function (internal error-catching or tracked
        telemetry), Listener wraps it with rate limiting.  BusService never touches
        the RateLimiter directly.

        For debounced listeners, the rate limiter spawns a background task that calls
        ``invoke_fn`` after the quiet period.  This method returns immediately after
        spawning — the handler fires later.

        Includes once-guard: if ``once=True`` and the listener has already fired,
        this method returns immediately.  This is the sole once-guard — callers
        that bypass BusService (e.g., test harness, command executor) are protected.
        Safe without a lock — no ``await`` between check-and-set.
        """
        if self.once and self._fired:
            return
        if self.once:
            self.mark_fired()

        if self._rate_limiter:
            await self._rate_limiter.call(invoke_fn)
        else:
            await invoke_fn()

    def cancel(self) -> None:
        """Cancel the listener: set the cancelled flag and stop any pending rate limiter tasks.

        The ``_cancelled`` flag signals a pending ``_register_then_add_route`` task
        to skip route insertion, preventing orphaned listeners when
        ``Subscription.cancel()`` races with the async add task (#451).

        Also cancels any active rate limiter (debounce/throttle) tasks.
        This is the sole cancellation path — external code must not call
        ``_rate_limiter.cancel()`` directly.

        Terminal operation: the listener must not be reused after this call.
        """
        self._cancelled = True
        if self._rate_limiter:
            self._rate_limiter.cancel()
        if self._duration_timer:
            self._duration_timer.cancel()

    def matches(self, ev: "Event[Any]") -> bool:
        """Check if the event matches the listener's predicate."""
        if self.predicate is None:
            return True
        matched = self.predicate(ev)

        match_str = "matched" if matched else "did not match"
        self.logger.debug("Listener %s %s predicate for event: %s", self, match_str, ev)
        return matched

    async def invoke(self, event: "Event[Any]") -> None:
        """Invoke the handler with dependency injection."""
        kwargs = self._injector.inject_parameters(event, **(self.kwargs or {}))
        await self._async_handler(**kwargs)

    def __repr__(self) -> str:
        return f"Listener<{self.owner_id} - {self.handler_short_name}>"

    @staticmethod
    def _validate_options(
        once: bool,
        debounce: float | None,
        throttle: float | None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        duration: float | None = None,
    ) -> None:
        if debounce is not None and debounce <= 0:
            raise ValueError("'debounce' must be a positive number")
        if throttle is not None and throttle <= 0:
            raise ValueError("'throttle' must be a positive number")
        if debounce is not None and throttle is not None:
            raise ValueError("Cannot specify both 'debounce' and 'throttle' parameters")
        if once and (debounce is not None or throttle is not None):
            raise ValueError("Cannot combine 'once=True' with 'debounce' or 'throttle'")
        if timeout is not None and (isinstance(timeout, bool) or timeout <= 0):
            raise ValueError("timeout must be a positive number")
        if timeout_disabled and timeout is not None:
            raise ValueError("Cannot specify both 'timeout' and 'timeout_disabled=True'")
        if duration is not None and duration <= 0:
            raise ValueError("'duration' must be a positive number")
        if duration is not None and debounce is not None:
            raise ValueError("Cannot combine 'duration' with 'debounce'")
        if duration is not None and throttle is not None:
            raise ValueError("Cannot combine 'duration' with 'throttle'")

    @classmethod
    def create(
        cls,
        task_bucket: "TaskBucket",
        owner_id: str,
        topic: str,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        once: bool = False,
        debounce: float | None = None,
        throttle: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        priority: int = 0,
        logger: Logger = LOGGER,
        app_key: str = "",
        instance_index: int = 0,
        name: str | None = None,
        source_tier: SourceTier = "app",
        immediate: bool = False,
        duration: float | None = None,
        entity_id: str | None = None,
        is_attribute_listener: bool = False,
        hold_predicate: "Predicate | None" = None,
    ) -> "Listener":
        cls._validate_options(
            once=once,
            debounce=debounce,
            throttle=throttle,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            duration=duration,
        )
        if duration is not None and not entity_id:
            raise ValueError("'duration' requires an entity_id — use on_state_change() or on_attribute_change()")
        if immediate and not entity_id:
            raise ValueError("'immediate' requires an entity_id — use on_state_change() or on_attribute_change()")

        pred = normalize_where(where)
        signature = get_typed_signature(handler)
        handler_name = callable_name(handler)
        parts = handler_name.rsplit(".", 1)
        short_name = parts[-1] if parts else handler_name

        # Create async handler and injector
        async_handler = make_async_handler(handler, task_bucket)
        injector = ParameterInjector(handler_name, signature)

        listener = cls(
            logger=logger,
            owner_id=owner_id,
            app_key=app_key,
            instance_index=instance_index,
            topic=topic,
            orig_handler=handler,
            _async_handler=async_handler,
            _injector=injector,
            predicate=pred,
            kwargs=kwargs,
            once=once,
            debounce=debounce,
            throttle=throttle,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            priority=priority,
            handler_name=handler_name,
            handler_short_name=short_name,
            name=name,
            source_tier=source_tier,
            immediate=immediate,
            duration=duration,
            entity_id=entity_id,
            hold_predicate=hold_predicate,
            is_attribute_listener=is_attribute_listener,
        )

        # One-time construction-phase init — _rate_limiter is set here (inside create()),
        # not by external callers, so it doesn't need a mark_* guard like db_id.
        if debounce is not None or throttle is not None:
            listener._rate_limiter = RateLimiter(
                task_bucket=task_bucket,
                debounce=debounce,
                throttle=throttle,
                handler_name=handler_name,
            )

        return listener


@dataclass(slots=True)
class Subscription:
    """A subscription to an event topic with a specific listener key.

    This class is used to manage the lifecycle of a listener, allowing it to be cancelled
    or managed within a context.
    """

    listener: Listener
    """The listener associated with this subscription."""

    unsubscribe: "Callable[[], None]"
    """Function to call to unsubscribe the listener."""

    def cancel(self) -> None:
        """Cancel the subscription by calling the unsubscribe function."""
        self.unsubscribe()


def make_async_handler(fn: "HandlerType", task_bucket: "TaskBucket") -> "AsyncHandlerType":
    """Wrap a function to ensure it is always called as an async handler.

    If the function is already an async function, it will be called directly.
    If it is a regular function, it will be run in an executor to avoid blocking the event loop.

    Args:
        fn: The function to adapt.
        task_bucket: TaskBucket used to create the async adapter (runs sync handlers in executor).

    Returns:
        An async handler that wraps the original function.
    """
    return cast("AsyncHandlerType", task_bucket.make_async_adapter(fn))
