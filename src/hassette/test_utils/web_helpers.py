"""Reusable factory functions for web-related test data.

These build manifest, snapshot, listener-metric, and registry objects
used by both e2e and integration web tests.
"""

from unittest.mock import MagicMock

from hassette.core.app_registry import AppFullSnapshot, AppInstanceInfo, AppManifestInfo


def make_full_snapshot(
    manifests: list[AppManifestInfo] | None = None,
    only_app: str | None = None,
) -> AppFullSnapshot:
    """Build an AppFullSnapshot from a list of manifests."""
    manifests = manifests or []
    counts = {"running": 0, "failed": 0, "stopped": 0, "disabled": 0, "blocked": 0}
    for m in manifests:
        if m.status in counts:
            counts[m.status] += 1
    return AppFullSnapshot(
        manifests=manifests,
        only_app=only_app,
        total=len(manifests),
        **counts,
    )


def make_manifest(
    app_key: str = "my_app",
    class_name: str = "MyApp",
    display_name: str = "My App",
    filename: str = "my_app.py",
    enabled: bool = True,
    auto_loaded: bool = False,
    status: str = "running",
    block_reason: str | None = None,
    instance_count: int = 1,
    instances: list[AppInstanceInfo] | None = None,
    error_message: str | None = None,
) -> AppManifestInfo:
    """Build an AppManifestInfo with sensible defaults."""
    return AppManifestInfo(
        app_key=app_key,
        class_name=class_name,
        display_name=display_name,
        filename=filename,
        enabled=enabled,
        auto_loaded=auto_loaded,
        status=status,
        block_reason=block_reason,
        instance_count=instance_count,
        instances=instances or [],
        error_message=error_message,
    )


def make_listener_metric(
    listener_id: int,
    owner: str,
    topic: str,
    handler_name: str,
    invocations: int = 10,
    successful: int = 9,
    failed: int = 1,
) -> MagicMock:
    """Build a mock listener metric with `.to_dict()` and direct attribute access."""
    d = {
        "listener_id": listener_id,
        "owner": owner,
        "topic": topic,
        "handler_name": handler_name,
        "total_invocations": invocations,
        "successful": successful,
        "failed": failed,
        "di_failures": 0,
        "cancelled": 0,
        "total_duration_ms": invocations * 2.0,
        "min_duration_ms": 1.0,
        "max_duration_ms": 5.0,
        "avg_duration_ms": 2.0,
        "last_invoked_at": None,
        "last_error_message": None,
        "last_error_type": None,
    }
    m = MagicMock()
    m.to_dict.return_value = d
    # Expose attributes directly for bus_metrics_summary
    for k, v in d.items():
        setattr(m, k, v)
    return m


def setup_registry(hassette: MagicMock, manifests: list[AppManifestInfo] | None = None) -> None:
    """Configure the mock registry to return a proper AppFullSnapshot."""
    snapshot = make_full_snapshot(manifests)
    hassette._app_handler.registry.get_full_snapshot.return_value = snapshot
