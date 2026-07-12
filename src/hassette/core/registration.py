"""Registration dataclasses for listener and scheduled job records."""

from dataclasses import dataclass

from hassette.types.enums import DEFAULT_BACKPRESSURE_POLICY, DEFAULT_OVERLAP_MODE, BackpressurePolicy, ExecutionMode
from hassette.types.types import SourceTier


@dataclass(frozen=True)
class ListenerRegistration:
    """Describes a listener at the moment it is registered, for persistence."""

    app_key: str
    """Unique key for the app that owns this listener."""

    instance_index: int
    """Instance index of the app."""

    handler_method: str
    """Fully qualified name of the handler method."""

    topic: str
    """Event topic the listener is subscribed to."""

    debounce: float | None
    """Debounce window in seconds, or None."""

    throttle: float | None
    """Throttle window in seconds, or None."""

    once: bool
    """Whether the listener fires only once."""

    priority: int
    """Listener ordering priority."""

    predicate_description: str | None
    """Python repr of the listener's predicate, or None if no ``where=`` was given."""

    human_description: str | None
    """Stable, human-readable summary from predicate.summarize(), or None."""

    source_location: str
    """File and line number where the listener was registered (e.g. 'app.py:42')."""

    registration_source: str | None
    """Source code snippet of the registration call, or None if unavailable."""

    name: str | None = None
    """Optional stable name for the listener, used as the natural key escape hatch."""

    source_tier: SourceTier = "app"
    """Whether this listener originates from a user app or the framework itself."""

    immediate: bool = False
    """Whether the listener fires immediately with the current entity state on registration."""

    duration: float | None = None
    """Duration in seconds the entity must remain in the matching state before the handler fires."""

    entity_id: str | None = None
    """The entity this listener monitors, if applicable."""

    mode: ExecutionMode = DEFAULT_OVERLAP_MODE
    """Resolved overlap mode (single/restart/queued/parallel). Persisted to
    the ``listeners.mode`` column. The tier-aware default is already applied in the options."""

    backpressure: BackpressurePolicy = DEFAULT_BACKPRESSURE_POLICY
    """Configured backpressure policy (block/drop_newest). Persisted to the
    ``listeners.backpressure`` column."""


@dataclass(frozen=True)
class ScheduledJobRegistration:
    """Describes a scheduled job at the moment it is registered, for persistence."""

    app_key: str
    """Unique key for the app that owns this job."""

    instance_index: int
    """Instance index of the app."""

    job_name: str
    """Human-readable name for the job."""

    handler_method: str
    """Fully qualified name of the job callable."""

    trigger_type: str
    """Trigger kind: one of ``"interval"``, ``"cron"``, ``"once"``, ``"after"``, ``"custom"``."""

    trigger_label: str
    """Human-readable display label (from trigger.trigger_label()). Distinct from
    trigger_type (the DB-stable discriminator)."""

    trigger_detail: str | None
    """Optional human-readable detail string (from trigger.trigger_detail())."""

    args_json: str
    """JSON-serialized positional arguments."""

    kwargs_json: str
    """JSON-serialized keyword arguments."""

    source_location: str
    """File and line number where the job was registered."""

    registration_source: str | None
    """Source code snippet of the registration call, or None if unavailable."""

    source_tier: SourceTier = "app"
    """Whether this job originates from a user app or the framework itself."""

    group: str | None = None
    """Scheduler group name, or None if not assigned to a group."""

    mode: ExecutionMode = DEFAULT_OVERLAP_MODE
    """Resolved overlap mode (single/restart/queued/parallel). Persisted to
    the ``scheduled_jobs.mode`` column. The tier-aware default is already applied in the scheduler."""

    predicate_description: str | None = None
    """Python repr of the job's predicate, or None if no ``where=`` was given."""

    human_description: str | None = None
    """Stable, human-readable summary of the predicate — ``predicate.summarize()`` when
    available, otherwise ``callable_stable_name()`` as a fallback. None if no predicate."""
