"""Reusable factory functions for web-related test data.

These build manifest, snapshot, listener-metric, and registry objects
used by both e2e and integration web tests.

**Factory guide**:

- ``make_job()`` — builds a ``SimpleNamespace`` job stub with a real trigger object.
  Use for web/serialization tests that only need duck-typed attribute access.
- ``make_real_job()`` — builds a real ``ScheduledJob`` instance.
  Use for tests that exercise ``ScheduledJob.__post_init__``, ``matches()``,
  ``sort_index``, ``set_next_run``, or ``fire_at`` behavior.
"""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.core.app_registry import AppFullSnapshot, AppInstanceInfo, AppManifestInfo
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.triggers import After, Cron, Every, Once


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
    app_key: str,
    topic: str,
    handler_method: str,
    instance_index: int = 0,
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
        "app_key": app_key,
        "instance_index": instance_index,
        "topic": topic,
        "handler_method": handler_method,
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
    # Expose attributes directly for mock attribute access
    for k, v in d.items():
        setattr(m, k, v)
    return m


def setup_registry(hassette: MagicMock, manifests: list[AppManifestInfo] | None = None) -> None:
    """Configure the mock registry to return a proper AppFullSnapshot."""
    snapshot = make_full_snapshot(manifests)
    hassette._app_handler.registry.get_full_snapshot.return_value = snapshot


# ──────────────────────────────────────────────────────────────────────
# Scheduler job factory
# ──────────────────────────────────────────────────────────────────────


def make_job(
    job_id: str = "job-1",
    name: str = "check_lights",
    owner_id: str = "MyApp.MyApp[0]",
    next_run: str = "2024-01-01T00:05:00",
    cancelled: bool = False,
    trigger_type: str = "interval",
    trigger_detail: str | None = None,
    db_id: int | None = None,
    app_key: str = "",
    instance_index: int = 0,
) -> SimpleNamespace:
    """Build a ``SimpleNamespace`` scheduler job for test fixtures.

    Uses real trigger objects (``Every``, ``Cron``, ``Once``, ``After``) that
    implement ``TriggerProtocol`` so that ``resolve_trigger()`` works via the
    ``trigger_db_type()`` path.
    """
    trigger: object
    if trigger_type == "cron":
        cron_expr = trigger_detail or "0 0 * * *"
        trigger = Cron(cron_expr)
    elif trigger_type == "interval":
        seconds = 30
        if trigger_detail is not None:
            # Parse ISO 8601 duration like "PT30S" → 30 seconds
            m = re.search(r"(\d+)S", trigger_detail)
            if m:
                seconds = int(m.group(1))
        trigger = Every(seconds=seconds)
    elif trigger_type == "once":
        trigger = Once(at=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0))
    elif trigger_type == "after":
        trigger = After(seconds=30)
    else:
        trigger = None
    return SimpleNamespace(
        job_id=job_id,
        db_id=db_id,
        name=name,
        owner_id=owner_id,
        app_key=app_key,
        instance_index=instance_index,
        next_run=next_run,
        cancelled=cancelled,
        trigger=trigger,
    )


def make_real_job(
    name: str = "test_job",
    owner_id: str = "MyApp.MyApp[0]",
    trigger: object | None = None,
    jitter: float | None = None,
    group: str | None = None,
    app_key: str = "",
    instance_index: int = 0,
) -> ScheduledJob:
    """Build a real ``ScheduledJob`` instance for tests that need full object behavior.

    Use this instead of ``make_job()`` when the test exercises ``ScheduledJob.__post_init__``,
    ``matches()``, ``sort_index``, ``set_next_run``, or ``fire_at`` behavior.
    Use ``make_job()`` for web/serialization tests that only need duck-typed attribute access.

    Args:
        name: Job name. Defaults to ``"test_job"``.
        owner_id: Owner ID. Defaults to ``"MyApp.MyApp[0]"``.
        trigger: Optional trigger. Defaults to ``None``.
        jitter: Optional jitter in seconds.
        group: Optional group name.
        app_key: Optional app key.
        instance_index: Optional app instance index.
    """
    return ScheduledJob(
        owner_id=owner_id,
        next_run=date_utils.now(),
        job=lambda: None,
        name=name,
        trigger=trigger,  # pyright: ignore[reportArgumentType]
        jitter=jitter,
        group=group,
        app_key=app_key,
        instance_index=instance_index,
    )
