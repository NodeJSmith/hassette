"""Snapshot dataclasses for app instance and manifest state.

These are pure-data types produced by ``core.AppRegistry`` and consumed by
``hassette.web`` response mapping. Moving them to ``schemas`` (below both)
removes the ``web → core`` import cycle.
"""

from dataclasses import dataclass, field

from hassette.types.enums import ResourceStatus


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

    running: list[AppInstanceInfo] = field(default_factory=list)
    failed: list[AppInstanceInfo] = field(default_factory=list)
    only_app: str | None = None

    @property
    def total_count(self) -> int:
        return len(self.running) + len(self.failed)

    @property
    def running_count(self) -> int:
        """Number of running app instances."""
        return len(self.running)

    @property
    def failed_count(self) -> int:
        """Number of failed app instances."""
        return len(self.failed)

    @property
    def failed_apps(self) -> set[str]:
        """Set of app keys with failed instances."""
        return {info.app_key for info in self.failed}

    @property
    def running_apps(self) -> set[str]:
        """Set of app keys with running instances."""
        return {info.app_key for info in self.running}


@dataclass
class AppManifestInfo:
    """Snapshot of a single app manifest with derived runtime status."""

    app_key: str
    class_name: str
    display_name: str
    filename: str
    enabled: bool
    auto_loaded: bool
    status: str  # "running", "failed", "stopped", "disabled", "blocked"
    block_reason: str | None = None
    instance_count: int = 0
    """Number of currently tracked instances (running or failed). 0 means none are tracked."""
    instances: list[AppInstanceInfo] = field(default_factory=list)
    error_message: str | None = None
    error_traceback: str | None = None


@dataclass
class AppFullSnapshot:
    """Full manifest-based snapshot including all configured apps."""

    manifests: list[AppManifestInfo] = field(default_factory=list)
    only_app: str | None = None
    total: int = 0
    running: int = 0
    failed: int = 0
    stopped: int = 0
    disabled: int = 0
    blocked: int = 0


__all__ = [
    "AppFullSnapshot",
    "AppInstanceInfo",
    "AppManifestInfo",
    "AppStatusSnapshot",
]
