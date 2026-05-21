"""Unit tests for telemetry_helpers."""

from types import SimpleNamespace

import pytest

from hassette.web.telemetry_helpers import compute_error_rate, format_handler_summary

# ---------------------------------------------------------------------------
# compute_error_rate
# ---------------------------------------------------------------------------


def test_compute_error_rate_zero_total_returns_zero() -> None:
    """When both totals are zero there is no activity — result must be 0.0."""
    result = compute_error_rate(
        total_invocations=0,
        total_executions=0,
        handler_errors=0,
        job_errors=0,
    )
    assert result == 0.0


def test_compute_error_rate_all_errors_returns_100() -> None:
    """Every invocation/execution failed — should return 100.0."""
    result = compute_error_rate(
        total_invocations=5,
        total_executions=5,
        handler_errors=5,
        job_errors=5,
    )
    assert result == pytest.approx(100.0)


def test_compute_error_rate_mixed_returns_correct_percentage() -> None:
    """Mixed success/failure — verifies denominator includes both sides."""
    # 9 failures out of 33 + 28 = 61 total → 9/61 * 100
    result = compute_error_rate(
        total_invocations=33,
        total_executions=28,
        handler_errors=3,
        job_errors=6,
    )
    expected = (9 / 61) * 100
    assert result == pytest.approx(expected)


def test_compute_error_rate_handler_only_errors() -> None:
    """Only handler errors, no job errors."""
    result = compute_error_rate(
        total_invocations=10,
        total_executions=5,
        handler_errors=2,
        job_errors=0,
    )
    expected = (2 / 15) * 100
    assert result == pytest.approx(expected)


def test_compute_error_rate_job_only_errors() -> None:
    """Only job errors, no handler errors."""
    result = compute_error_rate(
        total_invocations=10,
        total_executions=5,
        handler_errors=0,
        job_errors=3,
    )
    expected = (3 / 15) * 100
    assert result == pytest.approx(expected)


def test_compute_error_rate_no_errors_returns_zero() -> None:
    """Activity exists but no errors — result must be 0.0."""
    result = compute_error_rate(
        total_invocations=20,
        total_executions=10,
        handler_errors=0,
        job_errors=0,
    )
    assert result == 0.0


def test_compute_error_rate_invocations_only_no_executions() -> None:
    """Jobs present in system but none executed — denominator is invocations only."""
    result = compute_error_rate(
        total_invocations=10,
        total_executions=0,
        handler_errors=2,
        job_errors=0,
    )
    expected = (2 / 10) * 100
    assert result == pytest.approx(expected)


def test_compute_error_rate_executions_only_no_invocations() -> None:
    """Handlers present but never invoked — denominator is executions only."""
    result = compute_error_rate(
        total_invocations=0,
        total_executions=8,
        handler_errors=0,
        job_errors=1,
    )
    expected = (1 / 8) * 100
    assert result == pytest.approx(expected)


def test_compute_error_rate_clamped_to_100_when_errors_exceed_total() -> None:
    """Mismatched counters should not produce a rate above 100%."""
    result = compute_error_rate(
        total_invocations=5,
        total_executions=5,
        handler_errors=8,
        job_errors=7,
    )
    assert result == 100.0


# ---------------------------------------------------------------------------
# format_handler_summary
# ---------------------------------------------------------------------------


def make_listener(
    topic: str,
    human_description: str | None = None,
    predicate_description: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        topic=topic,
        human_description=human_description,
        predicate_description=predicate_description,
    )


def test_format_handler_summary_entity_with_human_description() -> None:
    listener = make_listener(
        topic="state_changed.binary_sensor.garage_door",
        human_description="→ open",
    )
    assert format_handler_summary(listener) == "binary_sensor.garage_door → open"


def test_format_handler_summary_entity_with_predicate_description() -> None:
    listener = make_listener(
        topic="state_changed.light.kitchen",
        predicate_description="EntityMatches(entity_id='light.kitchen')",
    )
    assert format_handler_summary(listener) == "light.kitchen EntityMatches(entity_id='light.kitchen')"


def test_format_handler_summary_entity_no_condition() -> None:
    listener = make_listener(topic="state_changed.binary_sensor.garage_door")
    assert format_handler_summary(listener) == "binary_sensor.garage_door"


def test_format_handler_summary_non_entity_topic() -> None:
    listener = make_listener(topic="call_service", human_description="service turn_on")
    assert format_handler_summary(listener) == "call_service service turn_on"


def test_format_handler_summary_non_entity_no_condition() -> None:
    listener = make_listener(topic="call_service")
    assert format_handler_summary(listener) == "call_service"


def test_format_handler_summary_wildcard_topic() -> None:
    listener = make_listener(topic="state_changed.*", human_description="state changed")
    assert format_handler_summary(listener) == "state_changed.* state changed"


def test_format_handler_summary_human_description_takes_precedence() -> None:
    listener = make_listener(
        topic="state_changed.light.kitchen",
        human_description="→ on",
        predicate_description="state == on",
    )
    assert format_handler_summary(listener) == "light.kitchen → on"
