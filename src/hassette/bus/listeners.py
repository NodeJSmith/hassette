import itertools
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from logging import Logger, getLogger
from typing import Any, cast

from hassette.bus.duration_timer import DurationTimer
from hassette.bus.injection import ParameterInjector
from hassette.bus.rate_limiter import RateLimiter
from hassette.event_handling.predicates import normalize_where
from hassette.types.types import SourceTier
from hassette.utils.func_utils import callable_name
from hassette.utils.type_utils import get_typed_signature

if typing.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from hassette import TaskBucket
    from hassette.events.base import Event
    from hassette.types import AsyncHandlerType, HandlerType, Predicate
    from hassette.types.types import BusErrorHandlerType

LOGGER = getLogger(__name__)

# next_id() is only called at listener creation time on the event loop thread.
# itertools.count.__next__ is C-atomic. No lock needed unless the project targets
# free-threaded CPython (PEP 703), which would require a broader concurrency audit.
seq = itertools.count(1)


def next_id() -> int:
    return next(seq)


# ---------------------------------------------------------------------------
# Sub-struct: ListenerIdentity
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ListenerIdentity:
    """Ownership and telemetry identity fields for a listener.

    Groups all 9 identity/telemetry fields that identify who registered a
    listener and where it came from. Used by the database layer for registration
    telemetry (ListenerRegistration DTO) and by the Bus for collision detection.
    """

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


# ---------------------------------------------------------------------------
# Sub-struct: ListenerOptions
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ListenerOptions:
    """Behavioral execution parameters for a listener.

    Groups all 6 behavioral timing/execution fields with self-contained
    validation. Adding a new option requires changes only here and in the code
    that reads it (AC#1).
    """

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


# ---------------------------------------------------------------------------
# Sub-struct: HandlerInvoker
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class HandlerInvoker:
    """Handler callable, async wrapper, injector, rate limiter, and once-guard.

    Owns the dispatch and invocation methods. Created via the HandlerInvoker.create()
    classmethod which constructs the async wrapper, injector, and rate limiter from
    the handler and options.
    """

    orig_handler: "HandlerType"
    """Original handler function provided by the user."""

    _async_handler: "AsyncHandlerType"
    """Async-wrapped handler function. Private — not part of the public API."""

    _injector: ParameterInjector
    """Parameter injector for dependency injection. Private — invoked by invoke()."""

    kwargs: Mapping[str, Any] | None
    """Keyword arguments to pass to the handler."""

    error_handler: "BusErrorHandlerType | None"
    """Optional per-listener error handler."""

    _app_error_handler_resolver: "Callable[[], BusErrorHandlerType | None] | None"
    """Closure that resolves the app-level error handler at dispatch time."""

    _rate_limiter: RateLimiter | None
    """Rate limiter for debounce/throttle. None when no rate limiting is configured."""

    once: bool = False
    """Whether this invoker fires only once. Copied from ListenerOptions at creation time."""

    _fired: bool = field(default=False, init=False)
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
            _async_handler=async_handler,
            _injector=injector,
            kwargs=kwargs,
            error_handler=error_handler,
            _app_error_handler_resolver=app_error_handler_resolver,
            _rate_limiter=rate_limiter,
            once=options.once,
        )

    def mark_fired(self) -> None:
        """Mark this once-invoker as having fired. Called by dispatch() and Listener.cancel()."""
        self._fired = True

    def set_app_error_handler_resolver(self, resolver: "Callable[[], BusErrorHandlerType | None]") -> None:
        """Set the closure that resolves the app-level error handler at dispatch time."""
        self._app_error_handler_resolver = resolver

    async def dispatch(self, invoke_fn: "Callable[[], Awaitable[None]]") -> None:
        """Apply rate limiting around the given invoke function.

        BusService builds the invoke function (internal error-catching or tracked
        telemetry), HandlerInvoker wraps it with rate limiting. BusService never
        touches the RateLimiter directly.

        Includes once-guard: if ``once=True`` and the invoker has already fired,
        this method returns immediately. Safe without a lock — no ``await`` between
        check-and-set.
        """
        if self.once and self._fired:
            return
        if self.once:
            self.mark_fired()

        if self._rate_limiter:
            await self._rate_limiter.call(invoke_fn)
        else:
            await invoke_fn()

    async def invoke(self, event: "Event[Any]") -> None:
        """Invoke the handler with dependency injection."""
        kwargs = self._injector.inject_parameters(event, **(self.kwargs or {}))
        await self._async_handler(**kwargs)


# ---------------------------------------------------------------------------
# Sub-struct: DurationConfig
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DurationConfig:
    """Duration-hold configuration and timer lifecycle for a listener.

    Groups all duration-hold declarative fields plus the timer reference.
    The timer is attached after construction via attach_timer(), which takes
    BusService-supplied dependencies. This makes the two-phase construction
    explicit rather than silent field mutation.

    ``duration`` is None when this config holds only entity_id/immediate fields
    without a full duration-hold setup (e.g., immediate-only registrations or
    bare entity_id tracking).
    """

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

    def attach_timer(
        self,
        task_bucket: "TaskBucket",
        owner_id: str,
        create_cancel_sub: "Callable[[], Subscription]",
        on_cancel: "Callable[[], None] | None" = None,
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


# ---------------------------------------------------------------------------
# Listener (composed)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Listener:
    """A listener for events with a specific topic and handler.

    Composes four focused sub-structs (identity, invoker, options, duration_config)
    plus routing fields (topic, predicate) and minimal runtime state (_cancelled, db_id).
    Total: 10 fields (AC#2).
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
        if self.invoker._rate_limiter:
            self.invoker._rate_limiter.cancel()
        if self.duration_config is not None and self.duration_config._timer is not None:
            self.duration_config._timer.cancel()

    def matches(self, ev: "Event[Any]") -> bool:
        """Check if the event matches the listener's predicate."""
        if self.predicate is None:
            return True
        matched = self.predicate(ev)

        match_str = "matched" if matched else "did not match"
        self.logger.debug("Listener %s %s predicate for event: %s", self, match_str, ev)
        return matched

    def __repr__(self) -> str:
        return f"Listener<{self.identity.owner_id} - {self.identity.handler_short_name}>"

    # ------------------------------------------------------------------
    # Temporary backward-compat shims (removed in T05)
    # These allow T02/T03 consumers to pass tests before T04/T05 migrate
    # all access paths to sub-struct paths.
    # ------------------------------------------------------------------

    # Identity field proxies
    @property
    def owner_id(self) -> str:
        return self.identity.owner_id

    @owner_id.setter
    def owner_id(self, value: str) -> None:
        object.__setattr__(self.identity, "owner_id", value)

    @property
    def app_key(self) -> str:
        return self.identity.app_key

    @app_key.setter
    def app_key(self, value: str) -> None:
        object.__setattr__(self.identity, "app_key", value)

    @property
    def instance_index(self) -> int:
        return self.identity.instance_index

    @instance_index.setter
    def instance_index(self, value: int) -> None:
        object.__setattr__(self.identity, "instance_index", value)

    @property
    def name(self) -> str | None:
        return self.identity.name

    @name.setter
    def name(self, value: str | None) -> None:
        object.__setattr__(self.identity, "name", value)

    @property
    def source_tier(self) -> SourceTier:
        return self.identity.source_tier

    @source_tier.setter
    def source_tier(self, value: SourceTier) -> None:
        object.__setattr__(self.identity, "source_tier", value)

    @property
    def handler_name(self) -> str:
        return self.identity.handler_name

    @handler_name.setter
    def handler_name(self, value: str) -> None:
        object.__setattr__(self.identity, "handler_name", value)

    @property
    def handler_short_name(self) -> str:
        return self.identity.handler_short_name

    @property
    def source_location(self) -> str:
        return self.identity.source_location

    @source_location.setter
    def source_location(self, value: str) -> None:
        object.__setattr__(self.identity, "source_location", value)

    @property
    def registration_source(self) -> str:
        return self.identity.registration_source

    @registration_source.setter
    def registration_source(self, value: str) -> None:
        object.__setattr__(self.identity, "registration_source", value)

    # Options field proxies
    @property
    def once(self) -> bool:
        return self.options.once

    @once.setter
    def once(self, value: bool) -> None:
        object.__setattr__(self.options, "once", value)

    @property
    def debounce(self) -> float | None:
        return self.options.debounce

    @debounce.setter
    def debounce(self, value: float | None) -> None:
        object.__setattr__(self.options, "debounce", value)

    @property
    def throttle(self) -> float | None:
        return self.options.throttle

    @throttle.setter
    def throttle(self, value: float | None) -> None:
        object.__setattr__(self.options, "throttle", value)

    @property
    def timeout(self) -> float | None:
        return self.options.timeout

    @property
    def timeout_disabled(self) -> bool:
        return self.options.timeout_disabled

    @property
    def priority(self) -> int:
        return self.options.priority

    @priority.setter
    def priority(self, value: int) -> None:
        object.__setattr__(self.options, "priority", value)

    # Invoker field proxies
    @property
    def orig_handler(self) -> "HandlerType":
        return self.invoker.orig_handler

    @property
    def error_handler(self) -> "BusErrorHandlerType | None":
        return self.invoker.error_handler

    @error_handler.setter
    def error_handler(self, value: "BusErrorHandlerType | None") -> None:
        object.__setattr__(self.invoker, "error_handler", value)

    @property
    def kwargs(self) -> Mapping[str, Any] | None:
        return self.invoker.kwargs

    @property
    def _async_handler(self) -> "AsyncHandlerType":
        return self.invoker._async_handler

    @property
    def _injector(self) -> ParameterInjector:
        return self.invoker._injector

    @property
    def _rate_limiter(self) -> RateLimiter | None:
        return self.invoker._rate_limiter

    @property
    def _fired(self) -> bool:
        return self.invoker._fired

    @property
    def _app_error_handler_resolver(self) -> "Callable[[], BusErrorHandlerType | None] | None":
        return self.invoker._app_error_handler_resolver

    @_app_error_handler_resolver.setter
    def _app_error_handler_resolver(self, value: "Callable[[], BusErrorHandlerType | None] | None") -> None:
        object.__setattr__(self.invoker, "_app_error_handler_resolver", value)

    # DurationConfig field proxies
    @property
    def duration(self) -> float | None:
        return self.duration_config.duration if self.duration_config else None

    @property
    def immediate(self) -> bool:
        return self.duration_config.immediate if self.duration_config else False

    @property
    def entity_id(self) -> str | None:
        return self.duration_config.entity_id if self.duration_config else None

    @property
    def is_attribute_listener(self) -> bool:
        return self.duration_config.is_attribute_listener if self.duration_config else False

    @property
    def hold_predicate(self) -> "Predicate | None":
        return self.duration_config.hold_predicate if self.duration_config else None

    @property
    def _duration_timer(self) -> "DurationTimer | None":
        return self.duration_config._timer if self.duration_config else None

    @_duration_timer.setter
    def _duration_timer(self, value: "DurationTimer | None") -> None:
        if self.duration_config is not None:
            object.__setattr__(self.duration_config, "_timer", value)
        elif value is not None:
            raise AttributeError("Cannot set _duration_timer without a duration_config")

    # Method forwards
    async def dispatch(self, invoke_fn: "Callable[[], Awaitable[None]]") -> None:
        """Delegate to invoker.dispatch(). Temporary shim — use listener.invoker.dispatch()."""
        await self.invoker.dispatch(invoke_fn)

    async def invoke(self, event: "Event[Any]") -> None:
        """Delegate to invoker.invoke(). Temporary shim — use listener.invoker.invoke()."""
        await self.invoker.invoke(event)

    def mark_fired(self) -> None:
        """Delegate to invoker.mark_fired(). Temporary shim — use listener.invoker.mark_fired()."""
        self.invoker.mark_fired()

    def set_app_error_handler_resolver(self, resolver: "Callable[[], BusErrorHandlerType | None]") -> None:
        """Delegate to invoker.set_app_error_handler_resolver(). Temporary shim."""
        self.invoker.set_app_error_handler_resolver(resolver)

    # Legacy rate_limiter property (previously exposed)
    @property
    def rate_limiter(self) -> RateLimiter | None:
        """Read-only access to the rate limiter. Use cancel() for lifecycle management."""
        return self.invoker._rate_limiter

    # ------------------------------------------------------------------
    # Validation (cross-concern — stays on Listener.create)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_options(
        once: bool,
        debounce: float | None,
        throttle: float | None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        duration: float | None = None,
    ) -> None:
        ListenerOptions(
            once=once,
            debounce=debounce,
            throttle=throttle,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
        )
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
        error_handler: "BusErrorHandlerType | None" = None,
        source_location: str = "",
        registration_source: str = "",
        # Sub-struct parameters (optional — when provided, used directly)
        identity: ListenerIdentity | None = None,
        options: ListenerOptions | None = None,
        invoker: HandlerInvoker | None = None,
        duration_config: DurationConfig | None = None,
    ) -> "Listener":
        """Create a Listener from individual kwargs or pre-built sub-structs.

        Accepts both individual keyword arguments (backward compatible with all
        57 test + 5 production call sites) and sub-struct parameters. When
        individual kwargs are provided, constructs sub-structs internally.

        Cross-concern validation (duration + debounce incompatibility) runs
        here since it spans two sub-structs.
        """
        if identity is not None:
            # Sub-struct path: use provided sub-structs directly
            assert options is not None, "options must be provided when identity is provided"
            assert invoker is not None, "invoker must be provided when identity is provided"

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

        # Individual kwargs path: construct sub-structs internally
        # Cross-concern validation (duration spans DurationConfig + ListenerOptions)
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
        handler_name = callable_name(handler)
        parts = handler_name.rsplit(".", 1)
        short_name = parts[-1] if parts else handler_name

        built_identity = ListenerIdentity(
            owner_id=owner_id,
            app_key=app_key,
            instance_index=instance_index,
            name=name,
            source_tier=source_tier,
            handler_name=handler_name,
            handler_short_name=short_name,
            source_location=source_location,
            registration_source=registration_source,
        )

        built_options = ListenerOptions(
            once=once,
            debounce=debounce,
            throttle=throttle,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            priority=priority,
        )

        built_invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=handler,
            kwargs=kwargs,
            options=built_options,
            error_handler=error_handler,
        )

        built_duration_config: DurationConfig | None = None
        if entity_id:
            # Create a DurationConfig whenever entity_id is provided, for backward compat.
            # duration may be None for immediate-only or bare entity_id tracking.
            built_duration_config = DurationConfig(
                entity_id=entity_id,
                duration=duration,
                immediate=immediate,
                is_attribute_listener=is_attribute_listener,
                hold_predicate=hold_predicate,
            )

        return cls(
            logger=logger,
            topic=topic,
            predicate=pred,
            identity=built_identity,
            invoker=built_invoker,
            options=built_options,
            duration_config=built_duration_config,
        )

    @classmethod
    def create_cancel_listener(
        cls,
        task_bucket: "TaskBucket",
        owner_id: str,
        topic: str,
        handler: "HandlerType",
        entity_id: str,  # noqa: ARG003 — API contract for T04 (AC#9)
        predicate: "Predicate | None" = None,
    ) -> "Listener":
        """Create a framework cancel-listener with sensible defaults.

        Produces a listener with source_tier='framework'. No rate limiter,
        no error handler, no duration config.
        """
        handler_name = callable_name(handler)
        parts = handler_name.rsplit(".", 1)
        short_name = parts[-1] if parts else handler_name

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
