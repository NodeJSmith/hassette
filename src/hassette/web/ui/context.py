"""Template context helpers for the Hassette Web UI."""

from typing import TYPE_CHECKING, Any

from hassette.config.helpers import VERSION
from hassette.web.utils import resolve_trigger

if TYPE_CHECKING:
    from hassette.core.runtime_query_service import RuntimeQueryService
    from hassette.scheduler.classes import ScheduledJob


def job_to_dict(job: "ScheduledJob", app_key: str | None = None, instance_index: int = 0) -> dict[str, Any]:
    """Serialize a ScheduledJob to a template-friendly dict."""
    trigger_type, trigger_detail = resolve_trigger(job)
    return {
        "name": job.name,
        "owner_id": job.owner_id,
        "app_key": app_key,
        "instance_index": instance_index,
        "next_run": str(job.next_run),
        "repeat": job.repeat,
        "cancelled": job.cancelled,
        "trigger_type": trigger_type,
        "trigger_detail": trigger_detail,
    }


def base_context(current_page: str) -> dict:
    """Build the common template context shared by all pages."""
    return {
        "current_page": current_page,
        "hassette_version": str(VERSION),
    }


def alert_context(runtime: "RuntimeQueryService") -> dict[str, Any]:
    """Build the alert banner context from current system state."""
    snapshot = runtime.get_all_manifests_snapshot()
    failed_apps = [
        {
            "app_key": m.app_key,
            "error_message": m.error_message,
            "error_traceback": m.error_traceback,
        }
        for m in snapshot.manifests
        if m.status == "failed"
    ]
    return {"failed_apps": failed_apps}
