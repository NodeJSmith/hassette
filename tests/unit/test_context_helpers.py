"""Unit tests for web UI context helpers."""

from hassette.web.telemetry_helpers import (
    classify_error_rate,
    classify_health_bar,
    extract_entity_from_topic,
)


class TestExtractEntityFromTopic:
    """extract_entity_from_topic parses entity_id from state_changed topics."""

    def test_standard_entity(self) -> None:
        assert extract_entity_from_topic("state_changed.binary_sensor.garage_door") == "binary_sensor.garage_door"

    def test_light_entity(self) -> None:
        assert extract_entity_from_topic("state_changed.light.kitchen") == "light.kitchen"

    def test_entity_with_underscores(self) -> None:
        assert extract_entity_from_topic("state_changed.sensor.outdoor_temperature_f") == "sensor.outdoor_temperature_f"

    def test_non_state_changed_topic(self) -> None:
        assert extract_entity_from_topic("call_service") is None

    def test_bare_state_changed(self) -> None:
        assert extract_entity_from_topic("state_changed") is None

    def test_state_changed_domain_only(self) -> None:
        # "state_changed.light" has a domain but no entity — still a valid
        # topic filter (matches all lights), so entity_id is domain-only.
        assert extract_entity_from_topic("state_changed.light") == "light"

    def test_wildcard_topic(self) -> None:
        assert extract_entity_from_topic("state_changed.*") is None

    def test_empty_string(self) -> None:
        assert extract_entity_from_topic("") is None


class TestClassifyErrorRate:
    """classify_error_rate maps error percentages to CSS class names."""

    def test_zero(self) -> None:
        assert classify_error_rate(0.0) == "good"

    def test_low(self) -> None:
        assert classify_error_rate(3.0) == "good"

    def test_medium(self) -> None:
        assert classify_error_rate(7.0) == "warn"

    def test_high(self) -> None:
        assert classify_error_rate(15.0) == "bad"

    def test_boundary_five(self) -> None:
        assert classify_error_rate(5.0) == "warn"

    def test_boundary_ten(self) -> None:
        assert classify_error_rate(10.0) == "bad"


class TestClassifyHealthBar:
    """classify_health_bar maps success rates to CSS class names."""

    def test_perfect(self) -> None:
        assert classify_health_bar(100.0) == "excellent"

    def test_good(self) -> None:
        assert classify_health_bar(97.0) == "good"

    def test_warning(self) -> None:
        assert classify_health_bar(92.0) == "warning"

    def test_critical(self) -> None:
        assert classify_health_bar(85.0) == "critical"

    def test_boundary_ninety_five(self) -> None:
        assert classify_health_bar(95.0) == "good"

    def test_boundary_ninety(self) -> None:
        assert classify_health_bar(90.0) == "warning"
