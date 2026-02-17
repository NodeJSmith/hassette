"""Reusable factory functions for web-related test data.

These build manifest, snapshot, listener-metric, and registry objects
used by both e2e and integration web tests.
"""

from types import SimpleNamespace
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
    error_traceback: str | None = None,
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
        error_traceback=error_traceback,
    )


def make_listener_metric(
    listener_id: int,
    owner: str,
    topic: str,
    handler_name: str,
    invocations: int = 10,
    successful: int = 9,
    failed: int = 1,
    predicate_description: str | None = None,
    debounce: float | None = None,
    throttle: float | None = None,
    once: bool = False,
    priority: int = 0,
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
        "predicate_description": predicate_description,
        "debounce": debounce,
        "throttle": throttle,
        "once": once,
        "priority": priority,
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


# ──────────────────────────────────────────────────────────────────────
# Old-style snapshot factories (for AppHandler.get_status_snapshot())
# ──────────────────────────────────────────────────────────────────────


def make_old_app_instance(
    app_key: str = "my_app",
    index: int = 0,
    instance_name: str = "MyApp[0]",
    class_name: str = "MyApp",
    status: str = "running",
    error_message: str | None = None,
    owner_id: str | None = None,
) -> SimpleNamespace:
    """Build a ``SimpleNamespace`` app entry for old-style snapshots."""
    return SimpleNamespace(
        app_key=app_key,
        index=index,
        instance_name=instance_name,
        class_name=class_name,
        status=SimpleNamespace(value=status),
        error_message=error_message,
        owner_id=owner_id,
    )


def make_old_snapshot(
    running: list[SimpleNamespace] | None = None,
    failed: list[SimpleNamespace] | None = None,
    only_app: str | None = None,
) -> SimpleNamespace:
    """Build an outer ``SimpleNamespace`` for ``AppHandler.get_status_snapshot()``.

    When *running* and *failed* are both ``None``, defaults to a single
    running ``make_old_app_instance()`` entry.  Counts are auto-computed.
    """
    if running is None and failed is None:
        running = [make_old_app_instance()]
    running = running or []
    failed = failed or []
    return SimpleNamespace(
        running=running,
        failed=failed,
        total_count=len(running) + len(failed),
        running_count=len(running),
        failed_count=len(failed),
        only_app=only_app,
    )


# ──────────────────────────────────────────────────────────────────────
# Scheduler job factory
# ──────────────────────────────────────────────────────────────────────


def make_job(
    job_id: str = "job-1",
    name: str = "check_lights",
    owner: str = "MyApp.MyApp[0]",
    next_run: str = "2024-01-01T00:05:00",
    repeat: bool = True,
    cancelled: bool = False,
    trigger_type: str = "interval",
    trigger_detail: str | None = None,
) -> SimpleNamespace:
    """Build a ``SimpleNamespace`` scheduler job for test fixtures."""
    trigger_attrs: dict[str, str] = {}
    if trigger_detail is not None:
        if trigger_type == "cron":
            trigger_attrs["cron_expression"] = trigger_detail
        else:
            trigger_attrs["interval"] = trigger_detail
    trigger_cls = type(trigger_type, (), trigger_attrs)()
    return SimpleNamespace(
        job_id=job_id,
        name=name,
        owner=owner,
        next_run=next_run,
        repeat=repeat,
        cancelled=cancelled,
        trigger=trigger_cls,
    )
