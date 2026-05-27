"""Shared helpers for telemetry computation and classification used by the JSON API layer."""

from logging import getLogger
from typing import TYPE_CHECKING, Any, Protocol

from hassette.web.models import ErrorRateClass, HealthStatus

LOGGER = getLogger(__name__)

ERROR_RATE_WARN_THRESHOLD = 5
ERROR_RATE_BAD_THRESHOLD = 10
HEALTH_GOOD_THRESHOLD = 95
HEALTH_WARNING_THRESHOLD = 90

if TYPE_CHECKING:
    from hassette.core.runtime_query_service import RuntimeQueryService


class _ListenerLike(Protocol):
    """Structural type for objects with listener summary fields."""

    topic: str
    human_description: str | None
    predicate_description: str | None


def compute_error_rate(
    total_invocations: int,
    total_executions: int,
    handler_errors: int,
    job_errors: int,
) -> float:
    """Compute error rate percentage from handler and job totals.

    The denominator is the combined count of handler invocations and job
    executions — both contribute to the user-visible activity total.  This
    prevents the denominator from being only one side of the equation (e.g.
    handler-only), which would misstate the real error rate.

    Args:
        total_invocations: Total handler invocations (includes successful, failed, timed-out).
        total_executions: Total job executions (includes successful, failed, timed-out).
        handler_errors: Total handler failures (errors + timed-out combined).
        job_errors: Total job failures (errors + timed-out combined).

    Returns:
        Error rate as a percentage in [0, 100].  Returns 0.0 when both totals
        are zero to avoid division by zero.
    """
    total = total_invocations + total_executions
    if total == 0:
        return 0.0
    failures = handler_errors + job_errors
    return min((failures / total) * 100, 100.0)


def classify_error_rate(rate: float) -> ErrorRateClass:
    """Map an error-rate percentage to a CSS class name.

    Thresholds: <5% = "good", 5-10% = "warn", >=10% = "bad".
    """
    if rate < ERROR_RATE_WARN_THRESHOLD:
        return "good"
    if rate < ERROR_RATE_BAD_THRESHOLD:
        return "warn"
    return "bad"


def classify_health_bar(success_rate: float) -> HealthStatus:
    """Map a success-rate percentage to a CSS class name.

    Thresholds: 100% = "excellent", >=95% = "good",
    >=90% = "warning", <90% = "critical".
    """
    if success_rate >= 100:
        return "excellent"
    if success_rate >= HEALTH_GOOD_THRESHOLD:
        return "good"
    if success_rate >= HEALTH_WARNING_THRESHOLD:
        return "warning"
    return "critical"


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


def format_handler_summary(listener: _ListenerLike) -> str:
    """Generate a compact trigger description from listener metadata.

    Produces chip-friendly output suitable for UI display.

    Examples:
        - ``"binary_sensor.garage_door → open"``
        - ``"call_service service turn_on"``
    """
    entity_id = extract_entity_from_topic(listener.topic)
    condition = listener.human_description or listener.predicate_description or ""
    if entity_id:
        parts = [entity_id]
        if condition:
            parts.append(condition)
        return " ".join(parts)
    parts = [listener.topic]
    if condition:
        parts.append(condition)
    return " ".join(parts)
