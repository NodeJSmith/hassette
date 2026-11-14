"""Arrange ``AppRegistry`` instance entries through ``set_status``, its only writer."""

from typing import Any

from hassette_wire import ResourceStatus

from hassette.core.app_registry import AppRegistry
from hassette.schemas.app_snapshots import NeedsRestartInfo
from hassette.utils import date_utils


def seed_running(
    registry: AppRegistry, app_key: str, app: Any, status: ResourceStatus = ResourceStatus.RUNNING
) -> None:
    """Register ``app`` under its own ``instance_name``, then move it to ``status`` (RUNNING by default)."""
    registry.set_status(app_key, app.instance_name, ResourceStatus.NOT_STARTED, app=app)
    if status is not ResourceStatus.NOT_STARTED:
        registry.set_status(app_key, app.instance_name, status)


def seed_failed(
    registry: AppRegistry,
    app_key: str,
    instance_name: str,
    error: Exception | None = None,
    *,
    needs_restart: str | NeedsRestartInfo | None = None,
    pending_tasks: tuple[str, ...] = (),
) -> None:
    """Record a FAILED entry, flagged needs-restart when ``needs_restart`` gives a reason (or a full flag)."""
    flag = (
        NeedsRestartInfo(reason=needs_restart, pending_tasks=pending_tasks, flagged_at=date_utils.now())
        if isinstance(needs_restart, str)
        else needs_restart
    )
    registry.set_status(
        app_key,
        instance_name,
        ResourceStatus.FAILED,
        error=error or RuntimeError(f"{app_key}[{instance_name}] failed"),
        needs_restart=flag,
    )
