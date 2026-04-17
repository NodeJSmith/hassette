"""Registration dataclasses for listener and scheduled job records."""

from dataclasses import dataclass

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
    """Human-readable description of the predicate, or None."""

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

    trigger_type: str | None
    """Trigger kind: one of ``"interval"``, ``"cron"``, ``"once"``, ``"after"``, ``"custom"``,
    or ``None`` for legacy no-trigger jobs registered without a ``TriggerProtocol`` trigger.
    """

    trigger_label: str
    """Short stable label for telemetry / UI display (from trigger.trigger_label())."""

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
