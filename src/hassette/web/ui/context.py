"""Template context helpers for the Hassette Web UI."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol

from hassette.config.helpers import VERSION
from hassette.core.telemetry_models import AppHealthSummary, JobSummary, ListenerSummary

if TYPE_CHECKING:
    from hassette.core.runtime_query_service import RuntimeQueryService
    from hassette.core.telemetry_query_service import TelemetryQueryService


class _ListenerLike(Protocol):
    """Structural type for objects with listener summary fields."""

    topic: str
    human_description: str | None
    predicate_description: str | None


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


def extract_entity_from_topic(topic: str) -> str | None:
    """Extract entity_id from a state_changed topic string.

    Returns the entity_id portion (e.g. ``"binary_sensor.garage_door"``)
    for topics like ``"state_changed.binary_sensor.garage_door"``.
    Returns ``None`` for non-state-changed topics, empty strings,
    or wildcard patterns.
    """
    if not topic or not topic.startswith("state_changed."):
        return None
    remainder = topic[len("state_changed.") :]
    if not remainder or "*" in remainder:
        return None
    return remainder


def compute_health_metrics(
    listeners: list[ListenerSummary],
    jobs: list[JobSummary],
) -> dict[str, Any]:
    """Compute health strip metrics from listener and job summaries.

    Returns a dict with ``error_rate``, ``avg_duration``, and ``last_activity_ts``.
    """
    total_invocations = sum(ls.total_invocations for ls in listeners)
    total_errors = sum(ls.failed for ls in listeners)
    error_rate = (total_errors / total_invocations * 100) if total_invocations > 0 else 0.0
    all_avg = [ls.avg_duration_ms for ls in listeners if ls.avg_duration_ms > 0]
    avg_duration = sum(all_avg) / len(all_avg) if all_avg else 0.0
    last_times: list[float] = [ls.last_invoked_at for ls in listeners if ls.last_invoked_at]
    last_times.extend(j.last_executed_at for j in jobs if j.last_executed_at)
    last_activity_ts = max(last_times) if last_times else None
    return {
        "error_rate": error_rate,
        "avg_duration": avg_duration,
        "last_activity_ts": last_activity_ts,
    }


def format_handler_summary(listener: _ListenerLike) -> str:
    """Generate a human-readable trigger description from listener metadata.

    Examples:
        - ``"Fires when binary_sensor.garage_door → open"``
        - ``"Fires on call_service"``
    """
    entity_id = extract_entity_from_topic(listener.topic)
    condition = listener.human_description or listener.predicate_description or ""
    if entity_id:
        parts = ["Fires when", entity_id]
        if condition:
            parts.append(condition)
        return " ".join(parts)
    parts = ["Fires on", listener.topic]
    if condition:
        parts.append(condition)
    return " ".join(parts)


def safe_session_id(runtime: "RuntimeQueryService") -> int | None:
    """Return the current session_id from Hassette, or None if unavailable."""
    try:
        return runtime.hassette.session_id
    except (AttributeError, RuntimeError):
        return None


async def compute_app_grid_health(
    manifests: Sequence[Any],
    telemetry: "TelemetryQueryService",
) -> dict[str, AppHealthSummary]:
    """Compute per-app health metrics for the dashboard grid.

    Uses a single batch query (2 SQL statements) instead of 2N per-app queries.
    Returns a dict keyed by app_key with ``AppHealthSummary`` models.
    """
    try:
        summaries = await telemetry.get_all_app_summaries()
    except Exception:
        summaries = {}

    # Only include apps that appear in the manifest list.
    manifest_keys = {m.app_key for m in manifests}
    empty = AppHealthSummary(
        handler_count=0,
        job_count=0,
        total_invocations=0,
        total_errors=0,
        total_executions=0,
        total_job_errors=0,
        avg_duration_ms=0.0,
        last_activity_ts=None,
    )
    return {key: summaries.get(key, empty) for key in manifest_keys}
