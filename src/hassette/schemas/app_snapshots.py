"""Snapshot dataclasses for app instance and manifest state.

These are pure-data types produced by ``core.AppRegistry`` and consumed by
``hassette.web`` response mapping. Moving them to ``schemas`` (below both)
removes the ``web → core`` import cycle.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from hassette.types.enums import ManifestStatus, ResourceStatus

MANIFEST_STATUS_KEYS = tuple(ManifestStatus)


@dataclass
class AppInstanceInfo:
    """Snapshot of a single app instance for status queries."""

    app_key: str
    index: int
    instance_name: str
    class_name: str
    status: ResourceStatus
    error: Exception | None = None
    error_message: str | None = None
    error_traceback: str | None = None
    owner_id: str | None = None


@dataclass
class AppStatusSnapshot:
    """Immutable snapshot of all app states for web UI consumption."""

    instances: list[AppInstanceInfo] = field(default_factory=list)
    only_apps: list[str] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.instances)

    @property
    def running_count(self) -> int:
        """Number of running app instances."""
        return sum(1 for i in self.instances if i.error is None)

    @property
    def failed_count(self) -> int:
        """Number of failed app instances."""
        return sum(1 for i in self.instances if i.error is not None)

    @property
    def failed_apps(self) -> set[str]:
        """Set of app keys with failed instances."""
        return {i.app_key for i in self.instances if i.error is not None}

    @property
    def running_apps(self) -> set[str]:
        """Set of app keys with running instances."""
        return {i.app_key for i in self.instances if i.error is None}


@dataclass
class AppManifestInfo:
    """Snapshot of a single app manifest with derived runtime status."""

    app_key: str
    class_name: str
    display_name: str
    filename: str
    enabled: bool
    auto_loaded: bool
    status: str  # "running", "failed", "stopped", "disabled", "blocked", "degraded"
    # Placed after `status` (not next to `enabled`, where it sits in AppManifest/AppManifestResponse)
    # because dataclass rules forbid a defaulted field before the non-default `status`.
    autostart: bool = True
    block_reason: str | None = None
    instance_count: int = 0
    """Number of currently tracked instances (running or failed). 0 means none are tracked."""
    instances: list[AppInstanceInfo] = field(default_factory=list)
    error_message: str | None = None
    error_traceback: str | None = None
    in_current_config: bool = True
    """True if the app is present in the currently-loaded config; False for DB-only/removed apps."""


@dataclass
class AppFullSnapshot:
    """Full manifest-based snapshot including all configured apps."""

    manifests: list[AppManifestInfo] = field(default_factory=list)
    only_apps: list[str] = field(default_factory=list)
    total: int = 0
    status_counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(ManifestStatus, 0))
    """Manifest counts keyed by ``ManifestStatus`` value (``running``, ``failed``, ``stopped``,
    ``disabled``, ``blocked``, ``degraded``)."""


def tally_manifest_statuses(manifests: Iterable[AppManifestInfo]) -> dict[str, int]:
    """Count manifests by status (``running``, ``failed``, ``stopped``, ``disabled``, ``blocked``,
    ``degraded``).

    Unrecognized status values are silently skipped rather than raising a ``KeyError`` — this
    tallies manifests from both the in-memory registry (status always one of the known values)
    and DB-sourced rows overlaid with runtime state, where a future/drifted status value should
    degrade gracefully instead of crashing the response.
    """
    counts: dict[str, int] = dict.fromkeys(MANIFEST_STATUS_KEYS, 0)
    for m in manifests:
        if m.status in counts:
            counts[m.status] += 1
    return counts


__all__ = [
    "MANIFEST_STATUS_KEYS",
    "AppFullSnapshot",
    "AppInstanceInfo",
    "AppManifestInfo",
    "AppStatusSnapshot",
    "tally_manifest_statuses",
]
