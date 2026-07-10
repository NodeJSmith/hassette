"""Unit tests for telemetry_helpers."""

from types import SimpleNamespace

import pytest

from hassette.web.telemetry_helpers import compute_error_rate, compute_success_rate, format_handler_summary


@pytest.mark.parametrize(
    ("invocations", "executions", "handler_err", "job_err", "expected"),
    [
        pytest.param(0, 0, 0, 0, 0.0, id="zero_total"),
        pytest.param(5, 5, 5, 5, 100.0, id="all_errors"),
        pytest.param(33, 28, 3, 6, (9 / 61) * 100, id="mixed"),
        pytest.param(10, 5, 2, 0, (2 / 15) * 100, id="handler_only"),
        pytest.param(10, 5, 0, 3, (3 / 15) * 100, id="job_only"),
        pytest.param(20, 10, 0, 0, 0.0, id="no_errors"),
        pytest.param(10, 0, 2, 0, (2 / 10) * 100, id="invocations_only"),
        pytest.param(0, 8, 0, 1, (1 / 8) * 100, id="executions_only"),
        pytest.param(5, 5, 8, 7, 100.0, id="clamped_over_100"),
    ],
)
def test_compute_error_rate(invocations: int, executions: int, handler_err: int, job_err: int, expected: float) -> None:
    result = compute_error_rate(
        total_invocations=invocations,
        total_executions=executions,
        handler_errors=handler_err,
        job_errors=job_err,
    )
    assert result == pytest.approx(expected)


def test_compute_success_rate_complements_error_rate() -> None:
    """Success is the exact complement of the error rate."""
    assert compute_success_rate(30.0) == pytest.approx(70.0)


def test_compute_success_rate_zero_error_is_full() -> None:
    """No errors means 100% success."""
    assert compute_success_rate(0.0) == 100.0


def test_compute_success_rate_clamped_error_yields_zero() -> None:
    """A clamped 100% error rate produces 0% success — never negative."""
    assert compute_success_rate(compute_error_rate(5, 5, 8, 7)) == 0.0


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
