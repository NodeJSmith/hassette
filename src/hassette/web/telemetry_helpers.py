"""Shared helpers for telemetry computation and classification used by the JSON API layer."""

from typing import Protocol

from hassette_wire import AppHealth, ErrorRateClass, HealthStatus

from hassette.schemas.summary_models import AppHealthAggregates

ERROR_RATE_WARN_THRESHOLD = 5
ERROR_RATE_BAD_THRESHOLD = 10
HEALTH_GOOD_THRESHOLD = 95
HEALTH_WARNING_THRESHOLD = 90


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


def compute_success_rate(error_rate: float) -> float:
    """Success rate as the complement of the already-clamped error rate.

    This is the single definition of "success = 100 - error".  Callers pass the
    value returned by :func:`compute_error_rate` rather than re-deriving success
    from raw counters, so the [0, 100] clamp is preserved in one place.
    """
    return 100.0 - error_rate


def classify_error_rate(error_rate: float) -> ErrorRateClass:
    """Map an error-rate percentage to a CSS class name.

    Below ``ERROR_RATE_WARN_THRESHOLD`` is "good", below ``ERROR_RATE_BAD_THRESHOLD`` is "warn",
    anything higher is "bad".
    """
    if error_rate < ERROR_RATE_WARN_THRESHOLD:
        return "good"
    if error_rate < ERROR_RATE_BAD_THRESHOLD:
        return "warn"
    return "bad"


def classify_health_bar(success_rate: float) -> HealthStatus:
    """Map a success-rate percentage to a CSS class name.

    100% is "excellent", at least ``HEALTH_GOOD_THRESHOLD`` is "good", at least
    ``HEALTH_WARNING_THRESHOLD`` is "warning", anything lower is "critical".
    """
    if success_rate >= 100:
        return "excellent"
    if success_rate >= HEALTH_GOOD_THRESHOLD:
        return "good"
    if success_rate >= HEALTH_WARNING_THRESHOLD:
        return "warning"
    return "critical"


def build_app_health(agg: AppHealthAggregates) -> AppHealth:
    """Build the served ``AppHealth`` from execution aggregates.

    The one place app health is computed, for both the per-instance and the per-app scope:
    scope only changes which executions ``agg`` covers. Timed-out executions count as failures.
    """
    error_rate = compute_error_rate(
        total_invocations=agg.total_invocations,
        total_executions=agg.total_executions,
        handler_errors=agg.handler_errors + agg.handler_timed_out,
        job_errors=agg.job_errors + agg.job_timed_out,
    )
    return AppHealth(
        error_rate=error_rate,
        error_rate_class=classify_error_rate(error_rate),
        health_status=classify_health_bar(compute_success_rate(error_rate)),
        last_activity_ts=agg.last_activity_ts,
        handler_avg_duration_ms=agg.handler_avg_duration_ms,
        job_avg_duration_ms=agg.job_avg_duration_ms,
    )


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
    head = entity_id or listener.topic
    return f"{head} {condition}" if condition else head
