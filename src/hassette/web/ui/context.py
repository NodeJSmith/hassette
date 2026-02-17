"""Template context helpers for the Hassette Web UI."""

from typing import TYPE_CHECKING, Any

from hassette.config.helpers import VERSION

if TYPE_CHECKING:
    from hassette.core.data_sync_service import DataSyncService


def base_context(current_page: str) -> dict:
    """Build the common template context shared by all pages."""
    return {
        "current_page": current_page,
        "hassette_version": str(VERSION),
    }


def alert_context(data_sync: "DataSyncService") -> dict[str, Any]:
    """Build the alert banner context from current system state."""
    snapshot = data_sync.get_all_manifests_snapshot()
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
