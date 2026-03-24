"""Shared helpers for telemetry computation and classification.

Extracted from ``web/ui/context.py`` so they can be used by both the
legacy Jinja2 partials (during migration) and the new JSON telemetry
endpoints.  No imports from ``web/ui/`` — this module is the source,
not the consumer.
"""

import logging
from typing import TYPE_CHECKING, Any, Protocol

from hassette.config.helpers import VERSION
from hassette.core.telemetry_models import JobSummary, ListenerSummary

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hassette.core.runtime_query_service import RuntimeQueryService


class _ListenerLike(Protocol):
    """Structural type for objects with listener summary fields."""

    topic: str
    human_description: str | None
    predicate_description: str | None


def classify_error_rate(rate: float) -> str:
    """Map an error-rate percentage to a CSS class name.

    Thresholds: <5% = "good", 5-10% = "warn", >=10% = "bad".
    """
    if rate < 5:
        return "good"
    if rate < 10:
        return "warn"
    return "bad"


def classify_health_bar(success_rate: float) -> str:
    """Map a success-rate percentage to a CSS class name.

    Thresholds: 100% = "excellent", >=95% = "good",
    >=90% = "warning", <90% = "critical".
    """
    if success_rate == 100:
        return "excellent"
    if success_rate >= 95:
        return "good"
    if success_rate >= 90:
        return "warning"
    return "critical"


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

    Returns a dict with ``error_rate``, ``handler_avg_duration``,
    ``job_avg_duration``, and ``last_activity_ts``.
    """
    total_invocations = sum(ls.total_invocations for ls in listeners)
    total_errors = sum(ls.failed for ls in listeners)
    error_rate = (total_errors / total_invocations * 100) if total_invocations > 0 else 0.0
    total_handler_duration = sum(ls.total_duration_ms for ls in listeners)
    handler_avg_duration = (total_handler_duration / total_invocations) if total_invocations > 0 else 0.0
    total_job_executions = sum(j.total_executions for j in jobs)
    total_job_duration = sum(j.total_duration_ms for j in jobs)
    job_avg_duration = (total_job_duration / total_job_executions) if total_job_executions > 0 else 0.0
    last_times: list[float] = [ls.last_invoked_at for ls in listeners if ls.last_invoked_at is not None]
    last_times.extend(j.last_executed_at for j in jobs if j.last_executed_at is not None)
    last_activity_ts = max(last_times) if last_times else None
    return {
        "error_rate": error_rate,
        "handler_avg_duration": handler_avg_duration,
        "job_avg_duration": job_avg_duration,
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
