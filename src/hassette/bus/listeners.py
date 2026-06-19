import asyncio
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
from hassette.execution_mode import ExecutionModeGuard
from hassette.types.enums import BackpressurePolicy, ExecutionMode, Outcome
from hassette.types.types import SourceTier
from hassette.utils.func_utils import callable_name, callable_short_name
from hassette.utils.type_utils import get_typed_signature

if typing.TYPE_CHECKING:
    from hassette import TaskBucket
    from hassette.events.base import Event
    from hassette.types import AsyncHandlerType, HandlerType, Predicate
    from hassette.types.types import BusErrorHandlerType

LOGGER = getLogger(__name__)

STALL_THRESHOLD_SECONDS: float = 60.0
"""How long a ``single``/``queued`` invocation may hold its guard before a stall WARNING fires.

Independent of the per-listener ``timeout`` (which still ultimately releases the guard via the
command executor). This is the ONLY WARNING in the execution-mode feature — suppressions and
drops stay at DEBUG.

The scheduler keeps its own ``STALL_THRESHOLD_SECONDS`` (``core/scheduler_service.py``) at the
same value so it does not import from the bus layer; ``test_stall_threshold_in_sync`` asserts the
two stay equal. Update both together.
"""

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

    mode: ExecutionMode = ExecutionMode.SINGLE
    """Overlap behavior when a trigger fires while a prior invocation still runs.

    ``single`` drops the re-fire, ``restart`` cancels-and-replaces, ``queued`` serializes,
    ``parallel`` runs concurrently. The tier-aware default (framework→parallel, app→single)
    is applied by the registration path, not by this dataclass default. Suppressed/dropped
    counts are live-only diagnostics held on the per-listener guard, reset on restart.
    """

    backpressure: BackpressurePolicy = BackpressurePolicy.BLOCK
    """Saturation policy for this listener when the dispatch concurrency semaphore is at capacity.

    ``block`` (default) waits for a slot, preserving today's behavior unchanged.
    ``drop_newest`` skips the event immediately when the bus is saturated — the handler is not
    invoked and one drop is recorded. Acts at the dispatch acquire gate, orthogonal to
    ``mode``/``debounce``/``throttle`` which act inside the invoker.
    """

    def __post_init__(self) -> None:
        # Coerce a raw string mode (arriving via the Options TypedDict or str ergonomics) into
        # the enum. An unknown value fails coercion — surface it as a clear ValueError.
        if not isinstance(self.mode, ExecutionMode):
            try:
                self.mode = ExecutionMode(self.mode)
            except ValueError as exc:
                valid = ", ".join(repr(m.value) for m in ExecutionMode)
                raise ValueError(f"Invalid execution mode {self.mode!r}; must be one of {valid}") from exc
        # Coerce a raw string backpressure policy the same way.
        if not isinstance(self.backpressure, BackpressurePolicy):
            try:
                self.backpressure = BackpressurePolicy(self.backpressure)
            except ValueError as exc:
                valid = ", ".join(repr(m.value) for m in BackpressurePolicy)
                raise ValueError(f"Invalid backpressure policy {self.backpressure!r}; must be one of {valid}") from exc
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

    task_bucket: "TaskBucket"
    """TaskBucket used to spawn the cancellable child handler task for non-parallel modes."""

    guard: ExecutionModeGuard
    """Per-listener overlap state machine. Owns the running-task reference and live counters."""

    mode: ExecutionMode
    """Resolved overlap mode. Copied from options so dispatch can branch without reading the guard's
    private state."""

    handler_short_name: str
    """Short handler name, captured for the stall WARNING and debug logs."""

    once: bool = False
    """Whether this invoker fires only once. Intentional copy of ListenerOptions.once —
    dispatch() needs this but cannot back-reference options without a circular dependency."""

    backpressure_dropped: int = 0
    """Count of events dropped at the dispatch acquire gate due to DROP_NEWEST backpressure.
    Incremented only in BusService.dispatch — one writer, on the event loop, no await between
    the locked() check and the increment. Live-only; resets on restart, never persisted."""

    fired: bool = field(default=False, init=False)
    """Guard for once=True: set before the first invocation to prevent double-fire."""

    pending_done: "set[asyncio.Future[None]]" = field(default_factory=set, init=False)
    """Unresolved per-invocation completion futures for non-parallel modes.

    Each ``run_with_mode`` call (single/restart/queued) parks its outer dispatch task on a future
    that resolves when the handler actually runs (or is dropped/released). A queued trigger accepted
    into the deque has no live child until drain time, so its future would hang forever if the
    listener is released first. ``release_guard`` resolves every remaining future here so those outer
    dispatch tasks unwind and ``_dispatch_pending`` settles."""

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
            task_bucket=task_bucket,
            guard=ExecutionModeGuard(options.mode),
            mode=options.mode,
            handler_short_name=callable_short_name(handler),
            once=options.once,
        )

    def mark_fired(self) -> None:
        """Mark this once-invoker as having fired. Called by dispatch() and Listener.cancel()."""
        self.fired = True

    def set_app_error_handler_resolver(self, resolver: "Callable[[], BusErrorHandlerType | None]") -> None:
        """Set the closure that resolves the app-level error handler at dispatch time."""
        self.app_error_handler_resolver = resolver

    async def dispatch(self, invoke_fn: Callable[[], Awaitable[None]]) -> None:
        """Apply the once-guard, rate limiter, and overlap mode around the given invoke function.

        Order: once-guard → rate limiter (whether to start) → mode guard (overlap of started
        invocations). BusService builds ``invoke_fn`` (tracked telemetry); HandlerInvoker wraps it.

        Once-guard: if ``once=True`` and the invoker has already fired, returns immediately. Safe
        without a lock — no ``await`` between check-and-set.

        Mode guard: ``parallel`` is a pass-through that awaits ``invoke_fn`` inline (byte-for-byte
        today's behavior, no child task). For ``single``/``restart``/``queued`` the guard receives a
        run-and-track callable that spawns a fresh child task through ``task_bucket``; this method
        then awaits that child so the outer dispatch task stays pending and remains counted by
        ``_dispatch_pending``. A ``restart`` cancellation of the child surfaces as ``CancelledError``
        inside the child only — it is swallowed here so the outer dispatch task does not crash.
        """
        if self.once and self.fired:
            return
        if self.once:
            self.mark_fired()

        if self.rate_limiter:
            await self.rate_limiter.call(lambda: self.run_with_mode(invoke_fn))
        else:
            await self.run_with_mode(invoke_fn)

    async def run_with_mode(self, invoke_fn: Callable[[], Awaitable[None]]) -> None:
        """Apply the overlap mode guard to a single started invocation.

        The outer dispatch task (counted by BusService's ``_dispatch_pending``) must stay pending
        until the handler ACTUALLY runs — including the ``queued`` case where the child is spawned
        later, at drain time. A per-invocation ``done`` future bridges that gap: ``run_and_track``
        resolves it when its spawned child completes; ``release_guard`` resolves any still-unresolved
        futures so a released-while-queued trigger does not hang the outer task forever.
        """
        if self.mode is ExecutionMode.PARALLEL:
            await invoke_fn()
            return

        # ``done`` resolves when this trigger's handler finishes (normal or cancelled), is dropped
        # by the guard, or is released before it ever ran. Awaiting it keeps the outer dispatch task
        # — and thus _dispatch_pending — counted across the whole wait, including queue time.
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()
        self.pending_done.add(done)

        def resolve_done() -> None:
            self.pending_done.discard(done)
            if not done.done():
                done.set_result(None)

        def run_and_track() -> asyncio.Task[None]:
            # The guard may call this now (RAN) or later at drain time (QUEUED_ACCEPTED). Either way,
            # resolve ``done`` once the spawned child settles, normally or via restart-cancellation.
            task = self.task_bucket.spawn(self.invocation_with_stall_watch(invoke_fn), name="bus:mode_invocation")
            task.add_done_callback(lambda _t: resolve_done())
            return task

        outcome = await self.guard.run(run_and_track)

        if outcome in (Outcome.SUPPRESSED, Outcome.DROPPED):
            # The factory was never called — no child will resolve ``done``; resolve it here.
            resolve_done()
            return
        # RAN: child already spawned, ``done`` resolves when it finishes.
        # QUEUED_ACCEPTED: child spawns at drain time (or release resolves ``done`` first).
        await done

    async def invocation_with_stall_watch(self, invoke_fn: Callable[[], Awaitable[None]]) -> None:
        """Run one handler invocation, emitting a WARNING if it holds the guard past the threshold."""
        watchdog = asyncio.get_running_loop().call_later(STALL_THRESHOLD_SECONDS, self.warn_stalled)
        try:
            await invoke_fn()
        finally:
            watchdog.cancel()

    def warn_stalled(self) -> None:
        """Emit the feature's stall WARNING: a non-parallel handler is still holding its guard."""
        LOGGER.warning(
            "Handler '%s' has held its %s execution-mode guard for over %.0fs and is still running",
            self.handler_short_name,
            self.mode.value,
            STALL_THRESHOLD_SECONDS,
        )

    def cancel(self) -> None:
        """Cancel any pending rate-limiter tasks."""
        if self.rate_limiter:
            self.rate_limiter.cancel()

    async def release_guard(self) -> None:
        """Release the execution-mode guard: cancel the in-flight task and drop queued factories.

        Called when a listener is cancelled or replaced so no event/listener/app references leak
        ``parallel`` listeners hold no guard state, so this is a cheap no-op for them.

        Queued triggers still parked in the guard's deque never spawn a child once released, so
        their outer dispatch tasks are parked on ``done`` futures that nothing else will resolve.
        Resolve every remaining one here so those tasks unwind and ``_dispatch_pending`` settles.
        """
        await self.guard.release()
        # Copy first: resolving discards from the set via the future's resolve_done closure.
        for done in list(self.pending_done):
            self.pending_done.discard(done)
            if not done.done():
                done.set_result(None)

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

        Sets _cancelled flag and calls invoker.mark_fired(). For once=True listeners, mark_fired()
        prevents the handler from starting on any in-flight dispatch task that has not yet checked
        the once-guard. For once=False listeners, mark_fired() has no effect on dispatch (the
        once-guard is not consulted); protection comes from release_guard() cancelling the in-flight
        child task — spawned asynchronously, so there is a small window before it takes effect.
        Also cancels the rate limiter and duration timer, and releases the execution-mode guard
        (cancelling any in-flight handler task and dropping queued factories) so no event/listener
        references leak.

        Terminal operation: the listener must not be reused after this call.
        """
        self._cancelled = True
        self.invoker.mark_fired()
        self.invoker.cancel()
        if self.duration_config is not None:
            self.duration_config.cancel_timer()
        # release_guard is async (it awaits the cancelled task's settling under a lock); cancel()
        # is sync, so spawn the release on the same bucket that runs handler tasks. For ``parallel``
        # listeners this is a cheap no-op; for the others it drops the in-flight task and queue.
        self.invoker.task_bucket.spawn(self.invoker.release_guard(), name="bus:release_guard")

    def config_matches(self, other: "Listener") -> bool:
        """Check whether two listeners represent the same logical configuration.

        Compares handler callable, filter predicate, timing options (once, debounce,
        throttle, timeout, timeout_disabled, priority), the execution mode, handler kwargs,
        per-registration error handler (by identity), and duration configuration scalars.

        Does not compare runtime state: listener_id, db_id, _cancelled, or the
        attached DurationTimer. Lambda/closure predicates and callable conditions
        compare by identity — two fresh lambdas with identical bodies will report
        drift. Use non-lambda predicates or if_exists='replace' to avoid this.
        """
        return (
            self.invoker.orig_handler == other.invoker.orig_handler
            and self.predicate == other.predicate
            and self.options.once == other.options.once
            and self.options.debounce == other.options.debounce
            and self.options.throttle == other.options.throttle
            and self.options.timeout == other.options.timeout
            and self.options.timeout_disabled == other.options.timeout_disabled
            and self.options.priority == other.options.priority
            and self.options.mode == other.options.mode
            and self.options.backpressure == other.options.backpressure
            and self.invoker.kwargs == other.invoker.kwargs
            and self.invoker.error_handler is other.invoker.error_handler
            and _duration_configs_match(self.duration_config, other.duration_config)
        )

    def diff_fields(self, other: "Listener") -> list[str]:
        """Return configuration field names that differ between two listeners.

        Compares the same fields as config_matches(). Returns a stable-ordered list
        of field names (e.g. 'handler', 'predicate', 'once', 'debounce', ...) for use
        in drift error messages.
        """
        changed: list[str] = []
        if self.invoker.orig_handler != other.invoker.orig_handler:
            changed.append("handler")
        if self.predicate != other.predicate:
            changed.append("predicate")
        if self.options.once != other.options.once:
            changed.append("once")
        if self.options.debounce != other.options.debounce:
            changed.append("debounce")
        if self.options.throttle != other.options.throttle:
            changed.append("throttle")
        if self.options.timeout != other.options.timeout:
            changed.append("timeout")
        if self.options.timeout_disabled != other.options.timeout_disabled:
            changed.append("timeout_disabled")
        if self.options.priority != other.options.priority:
            changed.append("priority")
        if self.options.mode != other.options.mode:
            changed.append("mode")
        if self.options.backpressure != other.options.backpressure:
            changed.append("backpressure")
        if self.invoker.kwargs != other.invoker.kwargs:
            changed.append("kwargs")
        if self.invoker.error_handler is not other.invoker.error_handler:
            changed.append("error_handler")
        if not _duration_configs_match(self.duration_config, other.duration_config):
            changed.append("duration_config")
        return changed

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

        # Cancel-listeners are source_tier='framework' but bypass _on_internal's tier-aware
        # resolution, so set parallel explicitly to match the framework-tier default. They fire at
        # most once per timer, so parallel is the safe internal default.
        options = ListenerOptions(mode=ExecutionMode.PARALLEL)

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


def _duration_configs_match(a: DurationConfig | None, b: DurationConfig | None) -> bool:
    """Compare two DurationConfig objects by their logical-configuration scalars.

    Both None → equal. One None, one non-None → not equal. Compares entity_id,
    duration, immediate, is_attribute_listener, and hold_predicate. Excludes the
    attached _timer (runtime state).
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return (
        a.entity_id == b.entity_id
        and a.duration == b.duration
        and a.immediate == b.immediate
        and a.is_attribute_listener == b.is_attribute_listener
        and a.hold_predicate == b.hold_predicate
    )


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
