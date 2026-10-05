from enum import StrEnum
from typing import Annotated

from hassette_wire.lenient import LenientValue, UnknownValue


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


OpenExecutionMode = Annotated[ExecutionMode | UnknownValue, LenientValue("ExecutionMode")]


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


OpenBackpressurePolicy = Annotated[BackpressurePolicy | UnknownValue, LenientValue("BackpressurePolicy")]


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


OpenResourceStatus = Annotated[ResourceStatus | UnknownValue, LenientValue("ResourceStatus")]


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


OpenManifestStatus = Annotated[ManifestStatus | UnknownValue, LenientValue("ManifestStatus")]


class ExecutionStatus(StrEnum):
    """Status values for handler invocations and job executions.

    Must stay in sync with the ``executions.status`` CHECK constraint.
    """

    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


OpenExecutionStatus = Annotated[ExecutionStatus | UnknownValue, LenientValue("ExecutionStatus")]


class ResourceRole(StrEnum):
    """The kind of framework component a status or service entry describes."""

    CORE = "core"
    """The framework itself rather than one of its components. Reserved; current servers do not
    report it."""

    BASE = "base"
    """A generic component with no more specific kind. Reserved; current servers do not report it.
    Treat it like ``resource``."""

    SERVICE = "service"
    """A long-running framework service that is supervised and restarted on failure, such as the
    Home Assistant connection or the database."""

    RESOURCE = "resource"
    """A framework component that runs for the life of its owner but is not supervised or restarted
    on its own."""

    APP = "app"
    """A user app instance."""

    UNKNOWN = "unknown"
    """A component whose kind is not classified. Reserved; current servers do not report it."""


OpenResourceRole = Annotated[ResourceRole | UnknownValue, LenientValue("ResourceRole")]


# Values must equal the server's scheduled_jobs.schedule_status CHECK constraint (parity-tested).
class ScheduleStatus(StrEnum):
    """Whether a scheduled job will run again on its own."""

    SCHEDULED = "scheduled"
    """The job has a concrete next automatic run."""

    WAITING = "waiting"
    """The job's next run time comes from an entity that currently reports no usable time. The job
    stays registered and resumes once the entity reports one."""

    COMPLETED = "completed"
    """The job will not run again automatically: every occurrence has run, or computing the next one
    failed (see ``ScheduleStatusReason.TRIGGER_ERROR``). It can still be run on demand."""

    MANUAL = "manual"
    """The job has no automatic schedule and only runs on demand."""


OpenScheduleStatus = Annotated[ScheduleStatus | UnknownValue, LenientValue("ScheduleStatus")]


# Values must equal the server's scheduled_jobs.schedule_status_reason CHECK constraint (parity-tested).
class ScheduleStatusReason(StrEnum):
    """Qualifies a ``ScheduleStatus`` when the status alone does not explain the job's state.

    Absent when the status needs no qualification.
    """

    LEGACY_UNKNOWN = "legacy_unknown"
    """The status was carried over from data recorded before schedule status existed and has not
    been confirmed since. It is replaced once the job's app registers the job again."""

    TRIGGER_ERROR = "trigger_error"
    """The job is ``completed`` because computing its next run raised an error, not because its
    schedule ran out."""


OpenScheduleStatusReason = Annotated[ScheduleStatusReason | UnknownValue, LenientValue("ScheduleStatusReason")]
