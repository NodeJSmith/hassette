from enum import StrEnum


class ExecutionMode(StrEnum):
    """Overlap behavior for a listener when a trigger fires while a prior invocation still runs."""

    SINGLE = "single"
    """Drop the re-fire while a prior invocation is still running."""

    RESTART = "restart"
    """Cancel the running invocation and start a new one."""

    QUEUED = "queued"
    """Serialize triggers, running them one at a time in arrival order."""

    PARALLEL = "parallel"
    """Run invocations concurrently with no overlap guard (today's behavior)."""


class BackpressurePolicy(StrEnum):
    """What a listener does when the *global* dispatch semaphore is saturated.

    The semaphore is shared by all listeners across all apps — saturation means
    the whole bus is at capacity, not that this listener alone is busy. This is
    distinct from per-listener rate controls (``debounce``, ``throttle``, ``mode``),
    which operate inside the handler invoker after a dispatch slot is acquired.
    """

    BLOCK = "block"
    """Wait for a dispatch slot — the default for all listeners.

    When the global semaphore is saturated, the dispatch loop blocks until a slot
    opens, then runs the handler. No events are lost; the cost is added latency.
    Omitting ``backpressure=`` on a subscription is identical to passing ``BLOCK``.
    """

    DROP_NEWEST = "drop_newest"
    """Skip this event when the global semaphore is saturated; never waits.

    The dispatch loop checks the semaphore without acquiring it. If saturated, no
    task is spawned, one drop is recorded on the listener, and the loop moves on.
    Under normal load (semaphore not locked), dispatches identically to ``BLOCK``.

    A ``DROP_NEWEST`` listener may not run at all during a sustained saturation
    period — every event it receives while the bus is full is dropped. Use ``BLOCK``
    for handlers that must run at least once, even under load.
    """


class ResourceStatus(StrEnum):
    """Enumeration for resource status."""

    NOT_STARTED = "not_started"
    """The resource has not been started yet."""

    STARTING = "starting"
    """The resource is in the process of starting."""

    RUNNING = "running"
    """The resource is currently running."""

    STOPPING = "stopping"
    """The resource is in the process of stopping."""

    STOPPED = "stopped"
    """The resource has been stopped without errors."""

    FAILED = "failed"
    """The resource has failed with a recoverable error."""

    CRASHED = "crashed"
    """The resource has crashed unexpectedly and cannot recover."""

    EXHAUSTED_DEAD = "exhausted_dead"
    """The service's restart budget is exhausted with no further restarts (permanent end state)."""

    EXHAUSTED_COOLING = "exhausted_cooling"
    """The service's restart budget is exhausted and a long cooldown is in progress."""


class ManifestStatus(StrEnum):
    """Enumeration for app manifest status values (manifest-scoped, distinct from ``ResourceStatus``)."""

    DISABLED = "disabled"
    """The app is disabled in configuration and will not start."""

    BLOCKED = "blocked"
    """The app was intentionally prevented from starting (see ``BlockReason``)."""

    DEGRADED = "degraded"
    """At least one instance is running and at least one instance has failed."""

    RUNNING = "running"
    """All tracked instances are running."""

    FAILED = "failed"
    """All tracked instances have failed and none are running."""

    STOPPED = "stopped"
    """The app has no tracked instances (not started, or intentionally stopped)."""


class ExecutionStatus(StrEnum):
    """Status values for handler invocations and job executions.

    Must stay in sync with the ``executions.status`` CHECK constraint.
    """

    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"
