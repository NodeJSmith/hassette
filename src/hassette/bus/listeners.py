import itertools
import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from logging import Logger, getLogger

from hassette_wire import BackpressurePolicy, ExecutionMode, SourceTier

from hassette.bus.duration_timer import DurationTimer
from hassette.bus.invoker import HandlerInvoker
from hassette.event_handling.predicates import AllOf, normalize_where
from hassette.event_handling.predicates.combinators import flatten_all_of
from hassette.exceptions import TaskBucketSealedError
from hassette.types.types import WhereClause
from hassette.utils.func_utils import callable_name, callable_short_name

if typing.TYPE_CHECKING:
    from hassette import TaskBucket
    from hassette.events.base import AnyEvent
    from hassette.types import HandlerType, Predicate

LOGGER = getLogger(__name__)

# In-memory routing ID, assigned at listener creation. This is the dispatch/dedup key
# used by router.py and bus_service.py — distinct from the database row id (``db_id``),
# which is assigned later at registration. itertools.count.__next__ is atomic at the C
# level, so no lock is needed even though listeners are only ever created on the event loop.
_listener_id_seq = itertools.count(1)


MATCHED = -1
"""``Listener.evaluate`` result: the event passed the listener's scope and every filter.

Every ``evaluate`` sentinel is negative, so a result ``>= 0`` is always a filter index."""

OUT_OF_SCOPE = -2
"""``Listener.evaluate`` result: the event failed the listener's scope (another entity, the default change filter)."""

_VERDICTS = {MATCHED: "matched", OUT_OF_SCOPE: "is out of scope"}
"""``Listener.evaluate`` results with a fixed debug-log wording; any other result is a filter index."""


def next_id() -> int:
    """Return the next in-memory listener routing ID from a process-wide counter.

    Returns:
        A unique, monotonically increasing integer starting at 1.
    """
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

    instance_name: str | None = None
    """App instance name, precomputed at registration time from the owning app's app_config.instance_name.
    None for framework-tier listeners and non-App owners."""

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
class EntityWatch:
    """The entity a listener tracks, plus its duration-hold settings; owns the timer lifecycle.

    Every ``on_state_change`` / ``on_attribute_change`` listener carries one, with or without a
    duration. The timer is attached via attach_timer().
    """

    entity_id: str
    """Entity ID this listener is tracking. Required — non-empty."""

    duration: float | None = None
    """Duration in seconds the entity must remain in the matching state before the handler fires.
    None for immediate-only or entity_id-only listeners."""

    immediate: bool = False
    """If True, fire the handler immediately with the current entity state on registration."""

    attribute: str | None = None
    """Attribute name an ``on_attribute_change`` listener tracks. None for state listeners."""

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
        """Return the attached DurationTimer. Raises RuntimeError if it has not been attached."""
        if self._timer is None:
            raise RuntimeError("timer not yet attached — call attach_timer() first")
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
        normalize_cancel_event: "Callable[[AnyEvent], AnyEvent] | None" = None,
    ) -> None:
        """Construct a DurationTimer and store it.

        BusService calls this method during registration, passing the
        cancel-subscription factory and on_cancel callback. Counter
        ownership stays in BusService.
        """
        if self._timer is not None:
            raise RuntimeError("timer already attached — call cancel() before re-attaching")
        if self.duration is None:
            raise RuntimeError("attach_timer() requires a non-None duration")
        self._timer = DurationTimer(
            task_bucket=task_bucket,
            duration=self.duration,
            predicates=self.hold_predicate,
            entity_id=self.entity_id,
            owner_id=owner_id,
            create_cancel_sub=create_cancel_sub,
            on_cancel=on_cancel,
            normalize_cancel_event=normalize_cancel_event,
        )


@dataclass(slots=True)
class Listener:
    """A listener for events with a specific topic and handler.

    Composes four focused sub-structs (identity, invoker, options, entity_watch)
    plus routing fields (topic, scope, predicate) and minimal runtime state.

    Two predicates select events. ``scope`` holds the filters a registration method built to say which events the
    listener is about (its entity, domain or service, and the default change filter); ``predicate`` holds the filters
    the caller wrote (``where``, ``changed_from``, ``changed_to``, a passed ``changed=``). An event rejected by
    ``predicate`` is a near-miss; one rejected by ``scope`` isn't.
    """

    logger: Logger
    """Logger for the listener."""

    topic: str
    """Topic the listener is subscribed to."""

    predicate: "Predicate | None"
    """The caller's filters. Its top-level conjuncts are ``filters``."""

    identity: ListenerIdentity
    """Ownership and telemetry identity fields."""

    invoker: HandlerInvoker
    """Handler callable, dispatch engine, and once-guard."""

    options: ListenerOptions
    """Behavioral execution parameters."""

    entity_watch: EntityWatch | None
    """The entity this listener tracks, with its duration-hold settings and timer. None for ``on()`` listeners."""

    scope: "AllOf | None" = None
    """Registration-built selection filters, evaluated first. None when the registration method built none."""

    listener_id: int = field(default_factory=next_id, init=False)
    """Unique identifier for the listener instance."""

    _cancelled: bool = field(default=False, init=False, repr=False)
    """Set by cancel() to signal that a pending add_listener task should skip route insertion."""

    db_id: int | None = field(default=None, init=False)
    """Database row ID for this listener. Set by the executor after persistence; None until then."""

    filters: "tuple[Predicate, ...]" = field(default=(), init=False)
    """``predicate``'s top-level conjuncts (nested ``AllOf``s flattened), the units a near-miss names. Derived."""

    def __post_init__(self) -> None:
        self.filters = flatten_all_of(self.predicate)

    @property
    def full_predicate(self) -> "Predicate | None":
        """``scope`` and ``predicate`` as one predicate, for the listener's registered description."""
        if self.scope is None:
            return self.predicate
        if self.predicate is None:
            return self.scope
        caller = self.predicate.predicates if isinstance(self.predicate, AllOf) else (self.predicate,)
        return AllOf((*self.scope.predicates, *caller))

    @property
    def is_cancelled(self) -> bool:
        """Whether this listener has been cancelled. Read-only — use cancel() to set."""
        return self._cancelled

    def mark_registered(self, db_id: int) -> None:
        """Set the database ID after persistence. One-time assignment by BusService."""
        if self.db_id is not None:
            self.logger.warning(
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

        Never raises on a sealed task bucket. Sealing is reachable only after a force-terminal
        teardown, which seals without running hooks; the guard release is then skipped with a
        debug log so bulk-removal loops still cancel every listener. Only that sealed rejection
        is absorbed — any other ``spawn()`` failure still propagates.

        Terminal operation: the listener must not be reused after this call.
        """
        self._cancelled = True
        self.invoker.mark_fired()
        # A removed listener records no more near-misses, from in-flight dispatches or its timer.
        self.invoker.report_drop = None
        self.invoker.cancel()
        if self.entity_watch is not None:
            self.entity_watch.cancel_timer()
        # release_guard is async (it awaits the cancelled task's settling under a lock); cancel()
        # is sync, so spawn the release on the same bucket that runs handler tasks. For ``parallel``
        # listeners this is a cheap no-op; for the others it drops the in-flight task and queue.
        try:
            self.invoker.task_bucket.spawn(self.invoker.release_guard(), name="bus:release_guard")
        except TaskBucketSealedError:
            # Accepted gap (force-terminal only): the bucket rejects new work, so the guard's
            # in-flight task and queued factories are left unreleased. _force_terminal() already
            # documents "stale subscriptions remain" for this same path; this is the same
            # acceptance, not a new one. Must not raise here — remove_listeners_by_owner()'s loop
            # depends on cancel() completing for every listener even when one hits this condition.
            # See TaskBucketSealedError for why this is caught rather than pre-checked via
            # is_sealed. spawn() closes the rejected coroutine itself.
            self.logger.debug("%s: task bucket sealed, skipping release_guard()", self)

    def config_matches(self, other: "Listener") -> bool:
        """Check whether two listeners represent the same logical configuration.

        Compares handler callable, scope and filter predicates, timing options (once, debounce,
        throttle, timeout, timeout_disabled, priority), the execution mode, handler kwargs,
        per-registration error handler (by identity), and entity-watch scalars.

        Does not compare runtime state: listener_id, db_id, _cancelled, or the
        attached DurationTimer. Lambda/closure predicates and callable conditions
        compare by identity — two fresh lambdas with identical bodies will report
        drift. Use non-lambda predicates or if_exists='replace' to avoid this.
        """
        return all(comparator(self, other) for _, comparator in _CONFIG_MATCH_FIELDS)

    def diff_fields(self, other: "Listener") -> list[str]:
        """Return configuration field names that differ between two listeners.

        Compares the same fields as config_matches(). Returns a stable-ordered list
        of field names (e.g. 'handler', 'predicate', 'once', 'debounce', ...) for use
        in drift error messages.
        """
        return [name for name, comparator in _CONFIG_MATCH_FIELDS if not comparator(self, other)]

    def evaluate(self, ev: "AnyEvent") -> int:
        """Test the event against ``scope``, then each of ``filters`` in order, stopping at the first that fails.

        Each predicate runs at most once, so the result names the rejecting filter without evaluating anything twice.

        Returns:
            ``MATCHED``, ``OUT_OF_SCOPE``, or the index in ``filters`` of the filter that rejected the event.

        Raises if a predicate raises — the caller (BusService.dispatch) handles
        isolation, telemetry recording, and error-handler routing.
        """
        if self.scope is None and not self.filters:
            return MATCHED
        result = MATCHED
        if self.scope is not None and not self.scope(ev):
            result = OUT_OF_SCOPE
        else:
            for index, filter_ in enumerate(self.filters):
                if not filter_(ev):
                    result = index
                    break
        self.logger.debug("Listener %s %s for event: %s", self, _VERDICTS.get(result, "rejected by a filter"), ev)
        return result

    def matches(self, ev: "AnyEvent") -> bool:
        """Whether the event passes ``scope`` and every filter. Raises if a predicate raises (see ``evaluate``)."""
        return self.evaluate(ev) == MATCHED

    def __repr__(self) -> str:
        return f"Listener<{self.identity.owner_id} - {self.identity.handler_short_name}>"

    @classmethod
    def create(
        cls,
        topic: str,
        identity: ListenerIdentity,
        options: ListenerOptions,
        invoker: HandlerInvoker,
        where: WhereClause = None,
        entity_watch: EntityWatch | None = None,
        logger: Logger = LOGGER,
        scope: "Sequence[Predicate]" = (),
    ) -> "Listener":
        """Create a Listener from pre-built sub-structs.

        ``scope`` takes the selection filters the registration method built; ``where`` the caller's filters.

        Cross-concern validation (duration + debounce incompatibility) runs
        here since it spans two sub-structs.
        """
        if entity_watch is not None and entity_watch.duration is not None:
            if options.debounce is not None:
                raise ValueError("Cannot combine 'duration' with 'debounce'")
            if options.throttle is not None:
                raise ValueError("Cannot combine 'duration' with 'throttle'")

        pred = normalize_where(where)
        return cls(
            logger=logger,
            topic=topic,
            scope=AllOf(tuple(scope)) if scope else None,
            predicate=pred,
            identity=identity,
            invoker=invoker,
            options=options,
            entity_watch=entity_watch,
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
        no error handler, no entity watch.
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
            scope=None,
            predicate=predicate,
            identity=identity,
            invoker=invoker,
            options=options,
            entity_watch=None,
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


def _entity_watches_match(a: EntityWatch | None, b: EntityWatch | None) -> bool:
    """Compare two EntityWatch objects by their logical-configuration scalars.

    Both None → equal. One None, one non-None → not equal. Compares entity_id,
    duration, immediate, attribute, and hold_predicate. Excludes the
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
        and a.attribute == b.attribute
        and a.hold_predicate == b.hold_predicate
    )


# Single source of truth for Listener.config_matches()/diff_fields(): each entry names a
# configuration field and how to compare it between two listeners, so the two methods can't
# drift out of sync on which fields they check.
_CONFIG_MATCH_FIELDS: tuple[tuple[str, Callable[["Listener", "Listener"], bool]], ...] = (
    ("handler", lambda a, b: a.invoker.orig_handler == b.invoker.orig_handler),
    ("scope", lambda a, b: a.scope == b.scope),
    ("predicate", lambda a, b: a.predicate == b.predicate),
    ("once", lambda a, b: a.options.once == b.options.once),
    ("debounce", lambda a, b: a.options.debounce == b.options.debounce),
    ("throttle", lambda a, b: a.options.throttle == b.options.throttle),
    ("timeout", lambda a, b: a.options.timeout == b.options.timeout),
    ("timeout_disabled", lambda a, b: a.options.timeout_disabled == b.options.timeout_disabled),
    ("priority", lambda a, b: a.options.priority == b.options.priority),
    ("mode", lambda a, b: a.options.mode == b.options.mode),
    ("backpressure", lambda a, b: a.options.backpressure == b.options.backpressure),
    ("kwargs", lambda a, b: a.invoker.kwargs == b.invoker.kwargs),
    ("error_handler", lambda a, b: a.invoker.error_handler is b.invoker.error_handler),
    ("entity_watch", lambda a, b: _entity_watches_match(a.entity_watch, b.entity_watch)),
)
