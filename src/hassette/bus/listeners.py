import itertools
import typing
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from logging import Logger, getLogger
from typing import Any, cast

from hassette.bus.duration_timer import DurationTimer
from hassette.bus.injection import ParameterInjector
from hassette.bus.rate_limiter import RateLimiter
from hassette.event_handling.predicates import normalize_where
from hassette.types.types import SourceTier
from hassette.utils.func_utils import callable_name, callable_short_name
from hassette.utils.type_utils import get_typed_signature

if typing.TYPE_CHECKING:
    from hassette import TaskBucket
    from hassette.events.base import Event
    from hassette.types import AsyncHandlerType, HandlerType, Predicate
    from hassette.types.types import BusErrorHandlerType

LOGGER = getLogger(__name__)

# In-memory routing ID, assigned at listener creation. This is the dispatch/dedup key
# used by router.py and bus_service.py — distinct from the database row id (``db_id``),
# which is assigned later at registration. itertools.count.__next__ is atomic at the C
# level, so no lock is needed even though listeners are only ever created on the event loop.
_listener_id_seq = itertools.count(1)


def next_id() -> int:
    return next(_listener_id_seq)


@dataclass(slots=True)
class ListenerIdentity:
    """Groups ownership and telemetry fields that identify who registered a listener and where it came from."""

    owner_id: str
    """Unique string identifier for the owner of the listener."""

    handler_name: str
    """Human-readable fully-qualified name for the handler, computed once at creation time."""

    handler_short_name: str
    """Short (last-segment) name for the handler, computed once at creation time."""

    app_key: str = ""
    """Configuration-level app key for DB registration (e.g., 'my_app'). Empty for non-App owners."""

    instance_index: int = 0
    """App instance index for DB registration. 0 for non-App owners."""

    name: str | None = None
    """Optional stable name for the listener (the name= escape hatch on Bus.on())."""

    source_tier: SourceTier = "app"
    """Whether this listener originates from a user app or the framework itself."""

    source_location: str = ""
    """Captured source location (file:line) of the user code that registered this listener."""

    registration_source: str = ""
    """Captured source code snippet of the registration call."""


@dataclass(slots=True)
class ListenerOptions:
    """Behavioral timing parameters (once, debounce, throttle, timeout, priority) with validation."""

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

    def __post_init__(self) -> None:
        if self.debounce is not None and self.debounce <= 0:
            raise ValueError("'debounce' must be a positive number")
        if self.throttle is not None and self.throttle <= 0:
            raise ValueError("'throttle' must be a positive number")
        if self.debounce is not None and self.throttle is not None:
            raise ValueError("Cannot specify both 'debounce' and 'throttle' parameters")
        if self.once and (self.debounce is not None or self.throttle is not None):
            raise ValueError("Cannot combine 'once=True' with 'debounce' or 'throttle'")
        if self.timeout is not None and (isinstance(self.timeout, bool) or self.timeout <= 0):
            raise ValueError("timeout must be a positive number")
        if self.timeout_disabled and self.timeout is not None:
            raise ValueError("Cannot specify both 'timeout' and 'timeout_disabled=True'")


@dataclass(slots=True)
class HandlerInvoker:
    """Owns handler invocation, async wrapping, parameter injection, rate limiting, and the once-guard."""

    orig_handler: "HandlerType"
    """Original handler function provided by the user."""

    async_handler: "AsyncHandlerType"
    """Async-wrapped handler function."""

    injector: ParameterInjector
    """Parameter injector for dependency injection."""

    kwargs: Mapping[str, Any] | None
    """Keyword arguments to pass to the handler."""

    error_handler: "BusErrorHandlerType | None"
    """Optional per-listener error handler."""

    app_error_handler_resolver: "Callable[[], BusErrorHandlerType | None] | None"
    """Closure that resolves the app-level error handler at dispatch time."""

    rate_limiter: RateLimiter | None
    """Rate limiter for debounce/throttle. None when no rate limiting is configured."""

    once: bool = False
    """Whether this invoker fires only once. Intentional copy of ListenerOptions.once —
    dispatch() needs this but cannot back-reference options without a circular dependency."""

    fired: bool = field(default=False, init=False)
    """Guard for once=True: set before the first invocation to prevent double-fire."""

    @classmethod
    def create(
        cls,
        task_bucket: "TaskBucket",
        handler: "HandlerType",
        kwargs: Mapping[str, Any] | None,
        options: ListenerOptions,
        error_handler: "BusErrorHandlerType | None" = None,
        app_error_handler_resolver: "Callable[[], BusErrorHandlerType | None] | None" = None,
    ) -> "HandlerInvoker":
        """Construct a HandlerInvoker from a handler and options.

        Builds the async wrapper, injector, and rate limiter. Copies options.once.

        Args:
            task_bucket: TaskBucket for async adapter and rate limiter.
            handler: The user-supplied handler callable.
            kwargs: Optional keyword arguments to pass to the handler.
            options: Behavioral options (once, debounce, throttle).
            error_handler: Optional per-listener error handler.
            app_error_handler_resolver: Closure for app-level error handler resolution.
        """
        handler_name = callable_name(handler)
        signature = get_typed_signature(handler)
        async_handler = make_async_handler(handler, task_bucket)
        injector = ParameterInjector(handler_name, signature)

        rate_limiter: RateLimiter | None = None
        if options.debounce is not None or options.throttle is not None:
            rate_limiter = RateLimiter(
                task_bucket=task_bucket,
                debounce=options.debounce,
                throttle=options.throttle,
                handler_name=handler_name,
            )

        return cls(
            orig_handler=handler,
            async_handler=async_handler,
            injector=injector,
            kwargs=kwargs,
            error_handler=error_handler,
            app_error_handler_resolver=app_error_handler_resolver,
            rate_limiter=rate_limiter,
            once=options.once,
        )

    def mark_fired(self) -> None:
        """Mark this once-invoker as having fired. Called by dispatch() and Listener.cancel()."""
        self.fired = True

    def set_app_error_handler_resolver(self, resolver: "Callable[[], BusErrorHandlerType | None]") -> None:
        """Set the closure that resolves the app-level error handler at dispatch time."""
        self.app_error_handler_resolver = resolver

    async def dispatch(self, invoke_fn: Callable[[], Awaitable[None]]) -> None:
        """Apply rate limiting around the given invoke function.

        BusService builds the invoke function (internal error-catching or tracked
        telemetry), HandlerInvoker wraps it with rate limiting. BusService never
        touches the RateLimiter directly.

        Includes once-guard: if ``once=True`` and the invoker has already fired,
        this method returns immediately. Safe without a lock — no ``await`` between
        check-and-set.
        """
        if self.once and self.fired:
            return
        if self.once:
            self.mark_fired()

        if self.rate_limiter:
            await self.rate_limiter.call(invoke_fn)
        else:
            await invoke_fn()

    def cancel(self) -> None:
        """Cancel any pending rate-limiter tasks."""
        if self.rate_limiter:
            self.rate_limiter.cancel()

    async def invoke(self, event: "Event[Any]") -> None:
        """Invoke the handler with dependency injection."""
        kwargs = self.injector.inject_parameters(event, **(self.kwargs or {}))
        await self.async_handler(**kwargs)


@dataclass(slots=True)
class DurationConfig:
    """Groups duration-hold configuration fields and owns the timer lifecycle; timer is attached via attach_timer()."""

    entity_id: str
    """Entity ID this duration listener is tracking. Required — non-empty."""

    duration: float | None = None
    """Duration in seconds the entity must remain in the matching state before the handler fires.
    None for immediate-only or entity_id-only listeners."""

    immediate: bool = False
    """If True, fire the handler immediately with the current entity state on registration."""

    is_attribute_listener: bool = False
    """True when this listener was registered via on_attribute_change."""

    hold_predicate: "Predicate | None" = None
    """State-value predicates only (excludes transition predicates like StateFrom, StateDidChange).
    Used by DurationTimer for cancel evaluation and fire-time recheck. None when not set."""

    _timer: "DurationTimer | None" = field(default=None, init=False)
    """Duration timer. Attached via attach_timer() during BusService registration."""

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("'entity_id' must be a non-empty string")
        if self.duration is not None and self.duration <= 0:
            raise ValueError("'duration' must be a positive number")

    @property
    def timer(self) -> "DurationTimer":
        """Return the attached DurationTimer. Asserts it has been attached."""
        assert self._timer is not None, "timer not yet attached — call attach_timer() first"
        return self._timer

    def cancel_timer(self) -> None:
        """Cancel the attached duration timer if present."""
        if self._timer is not None:
            self._timer.cancel()

    def attach_timer(
        self,
        task_bucket: "TaskBucket",
        owner_id: str,
        create_cancel_sub: "Callable[[], Subscription]",
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Construct a DurationTimer and store it.

        BusService calls this method during registration, passing the
        cancel-subscription factory and on_cancel callback. Counter
        ownership stays in BusService.
        """
        assert self._timer is None, "timer already attached — call cancel() before re-attaching"
        assert self.duration is not None, "attach_timer() requires a non-None duration"
        self._timer = DurationTimer(
            task_bucket=task_bucket,
            duration=self.duration,
            predicates=self.hold_predicate,
            entity_id=self.entity_id,
            owner_id=owner_id,
            create_cancel_sub=create_cancel_sub,
            on_cancel=on_cancel,
        )


@dataclass(slots=True)
class Listener:
    """A listener for events with a specific topic and handler.

    Composes four focused sub-structs (identity, invoker, options, duration_config)
    plus routing fields (topic, predicate) and minimal runtime state.
    """

    logger: Logger
    """Logger for the listener."""

    topic: str
    """Topic the listener is subscribed to."""

    predicate: "Predicate | None"
    """Predicate to filter events before invoking the handler."""

    identity: ListenerIdentity
    """Ownership and telemetry identity fields."""

    invoker: HandlerInvoker
    """Handler callable, dispatch engine, and once-guard."""

    options: ListenerOptions
    """Behavioral execution parameters."""

    duration_config: DurationConfig | None
    """Duration-hold configuration and timer. None for non-duration listeners."""

    listener_id: int = field(default_factory=next_id, init=False)
    """Unique identifier for the listener instance."""

    _cancelled: bool = field(default=False, init=False, repr=False)
    """Set by cancel() to signal that a pending add_listener task should skip route insertion."""

    db_id: int | None = field(default=None, init=False)
    """Database row ID for this listener. Set by the executor after persistence; None until then."""

    @property
    def is_cancelled(self) -> bool:
        """Whether this listener has been cancelled. Read-only — use cancel() to set."""
        return self._cancelled

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

    def cancel(self) -> None:
        """Cancel the listener: set the cancelled flag and stop any pending tasks.

        Sets _cancelled flag, calls invoker.mark_fired() to prevent handler invocation
        on any in-flight dispatch task, and cancels rate limiter and duration timer.

        Terminal operation: the listener must not be reused after this call.
        """
        self._cancelled = True
        self.invoker.mark_fired()
        self.invoker.cancel()
        if self.duration_config is not None:
            self.duration_config.cancel_timer()

    def matches(self, ev: "Event[Any]") -> bool:
        """Check if the event matches the listener's predicate."""
        if self.predicate is None:
            return True
        matched = self.predicate(ev)

        verdict = "matched" if matched else "did not match"
        self.logger.debug("Listener %s %s predicate for event: %s", self, verdict, ev)
        return matched

    def __repr__(self) -> str:
        return f"Listener<{self.identity.owner_id} - {self.identity.handler_short_name}>"

    @classmethod
    def create(
        cls,
        topic: str,
        identity: ListenerIdentity,
        options: ListenerOptions,
        invoker: HandlerInvoker,
        where: "Predicate | Sequence[Predicate] | None" = None,
        duration_config: DurationConfig | None = None,
        logger: Logger = LOGGER,
    ) -> "Listener":
        """Create a Listener from pre-built sub-structs.

        Cross-concern validation (duration + debounce incompatibility) runs
        here since it spans two sub-structs.
        """
        if duration_config is not None and duration_config.duration is not None:
            if options.debounce is not None:
                raise ValueError("Cannot combine 'duration' with 'debounce'")
            if options.throttle is not None:
                raise ValueError("Cannot combine 'duration' with 'throttle'")

        pred = normalize_where(where)
        return cls(
            logger=logger,
            topic=topic,
            predicate=pred,
            identity=identity,
            invoker=invoker,
            options=options,
            duration_config=duration_config,
        )

    @classmethod
    def create_cancel_listener(
        cls,
        task_bucket: "TaskBucket",
        owner_id: str,
        topic: str,
        handler: "HandlerType",
        predicate: "Predicate | None" = None,
    ) -> "Listener":
        """Create a framework cancel-listener with sensible defaults.

        Produces a listener with source_tier='framework'. No rate limiter,
        no error handler, no duration config.
        """
        handler_name = callable_name(handler)
        short_name = callable_short_name(handler)

        identity = ListenerIdentity(
            owner_id=owner_id,
            handler_name=handler_name,
            handler_short_name=short_name,
            source_tier="framework",
        )

        options = ListenerOptions()

        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=handler,
            kwargs=None,
            options=options,
            error_handler=None,
        )

        return cls(
            logger=LOGGER,
            topic=topic,
            predicate=predicate,
            identity=identity,
            invoker=invoker,
            options=options,
            duration_config=None,
        )


@dataclass(slots=True)
class Subscription:
    """A subscription to an event topic with a specific listener key.

    This class is used to manage the lifecycle of a listener, allowing it to be cancelled
    or managed within a context.
    """

    listener: Listener
    """The listener associated with this subscription."""

    unsubscribe: Callable[[], None]
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
