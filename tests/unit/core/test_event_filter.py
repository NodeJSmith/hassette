"""Unit tests for EventFilter.

Tests verify:
- should_skip returns False for events with no payload
- should_skip returns False for non-HassPayload events
- system_log debug call_service events are skipped
- Entity exclusion (exact match and glob)
- Domain exclusion (exact match and glob)
- _has_exclusions=False short-circuits entity/domain check (returns False)
- EventFilter is constructable without any BusService dependency
"""

import logging
from dataclasses import dataclass
from unittest.mock import MagicMock

from hassette.core.event_filter import EventFilter
from hassette.events import Event
from hassette.test_utils.factories import make_hass_event, make_hassette_event


def make_logger() -> logging.Logger:
    return logging.getLogger("test.event_filter")


def make_filter(
    excluded_domains: tuple[str, ...] | None = None,
    excluded_entities: tuple[str, ...] | None = None,
) -> EventFilter:
    return EventFilter(
        excluded_domains=excluded_domains,
        excluded_entities=excluded_entities,
        logger=make_logger(),
    )


def make_no_payload_event() -> Event:
    return Event(topic="hass.state_changed", payload=None)


@dataclass(slots=True, frozen=True)
class StateChangedData:
    entity_id: str
    domain: str | None = None


@dataclass(slots=True, frozen=True)
class CallServiceData:
    domain: str
    service: str
    service_data: dict


class TestNoPayloadAndNonHass:
    def test_no_payload_returns_false(self) -> None:
        """should_skip returns False when event has no payload."""
        ef = make_filter()
        event = make_no_payload_event()
        assert ef.should_skip("hass.state_changed", event) is False

    def test_non_hass_payload_returns_false(self) -> None:
        """should_skip returns False for non-HassPayload events (e.g. HassettePayload)."""
        ef = make_filter()
        event = make_hassette_event()
        assert ef.should_skip("hassette.ready", event) is False


class TestSystemLogFiltering:
    def test_system_log_debug_call_service_skipped(self) -> None:
        """call_service event targeting system_log at debug level is skipped."""
        data = CallServiceData(
            domain="system_log",
            service="write",
            service_data={"level": "debug"},
        )
        event = make_hass_event(event_type="call_service", data=data)
        ef = make_filter()
        assert ef.should_skip("hass.call_service", event) is True

    def test_system_log_non_debug_not_skipped(self) -> None:
        """call_service to system_log at non-debug level is NOT skipped."""
        data = CallServiceData(
            domain="system_log",
            service="write",
            service_data={"level": "warning"},
        )
        event = make_hass_event(event_type="call_service", data=data)
        ef = make_filter()
        assert ef.should_skip("hass.call_service", event) is False

    def test_call_service_other_domain_not_skipped(self) -> None:
        """call_service to a non-system_log domain is NOT skipped."""
        data = CallServiceData(
            domain="light",
            service="turn_on",
            service_data={"level": "debug"},
        )
        event = make_hass_event(event_type="call_service", data=data)
        ef = make_filter()
        assert ef.should_skip("hass.call_service", event) is False

    def test_system_log_bad_payload_shape_does_not_raise(self) -> None:
        """AttributeError during system_log check is caught; event is not skipped."""
        data = MagicMock(spec=[])  # no attributes — accessing .domain raises AttributeError
        event = make_hass_event(event_type="call_service", data=data)
        ef = make_filter()
        # Should not raise; returns False (no exclusions configured)
        result = ef.should_skip("hass.call_service", event)
        assert result is False


class TestNoExclusionsShortCircuit:
    def test_no_exclusions_returns_false_after_system_log_check(self) -> None:
        """With no exclusions configured, state_changed events are never skipped."""
        data = StateChangedData(entity_id="light.kitchen", domain="light")
        event = make_hass_event(event_type="state_changed", data=data)
        ef = make_filter(excluded_domains=None, excluded_entities=None)
        assert ef._has_exclusions is False
        assert ef.should_skip("hass.state_changed", event) is False

    def test_no_exclusions_missing_entity_domain_returns_false(self) -> None:
        """No entity_id or domain on payload, no exclusions — returns False."""
        event = make_hass_event(event_type="state_changed", data=None)
        ef = make_filter()
        assert ef.should_skip("hass.state_changed", event) is False


class TestEntityExclusion:
    def test_exact_entity_match_skipped(self) -> None:
        """Exact entity_id match causes the event to be skipped."""
        data = StateChangedData(entity_id="light.kitchen", domain="light")
        event = make_hass_event(event_type="state_changed", data=data)
        ef = make_filter(excluded_entities=("light.kitchen",))
        assert ef.should_skip("hass.state_changed", event) is True

    def test_non_matching_entity_not_skipped(self) -> None:
        """Different entity_id is not skipped by entity exclusion."""
        data = StateChangedData(entity_id="light.living_room", domain="light")
        event = make_hass_event(event_type="state_changed", data=data)
        ef = make_filter(excluded_entities=("light.kitchen",))
        assert ef.should_skip("hass.state_changed", event) is False

    def test_glob_entity_match_skipped(self) -> None:
        """Glob pattern for entity_id causes the event to be skipped."""
        data = StateChangedData(entity_id="light.kitchen_main", domain="light")
        event = make_hass_event(event_type="state_changed", data=data)
        ef = make_filter(excluded_entities=("light.kitchen*",))
        assert ef.should_skip("hass.state_changed", event) is True

    def test_glob_entity_no_match_not_skipped(self) -> None:
        """Glob pattern that doesn't match the entity_id does not skip."""
        data = StateChangedData(entity_id="light.living_room", domain="light")
        event = make_hass_event(event_type="state_changed", data=data)
        ef = make_filter(excluded_entities=("light.kitchen*",))
        assert ef.should_skip("hass.state_changed", event) is False


class TestDomainExclusion:
    def test_exact_domain_match_skipped(self) -> None:
        """Exact domain match causes the event to be skipped."""
        data = StateChangedData(entity_id="media_player.tv", domain="media_player")
        event = make_hass_event(event_type="state_changed", data=data)
        ef = make_filter(excluded_domains=("media_player",))
        assert ef.should_skip("hass.state_changed", event) is True

    def test_non_matching_domain_not_skipped(self) -> None:
        """Different domain is not skipped by domain exclusion."""
        data = StateChangedData(entity_id="light.kitchen", domain="light")
        event = make_hass_event(event_type="state_changed", data=data)
        ef = make_filter(excluded_domains=("media_player",))
        assert ef.should_skip("hass.state_changed", event) is False

    def test_glob_domain_match_skipped(self) -> None:
        """Glob pattern for domain causes the event to be skipped."""
        data = StateChangedData(entity_id="media_player.tv", domain="media_player")
        event = make_hass_event(event_type="state_changed", data=data)
        ef = make_filter(excluded_domains=("media_*",))
        assert ef.should_skip("hass.state_changed", event) is True

    def test_glob_domain_no_match_not_skipped(self) -> None:
        """Glob pattern that doesn't match the domain does not skip."""
        data = StateChangedData(entity_id="light.kitchen", domain="light")
        event = make_hass_event(event_type="state_changed", data=data)
        ef = make_filter(excluded_domains=("media_*",))
        assert ef.should_skip("hass.state_changed", event) is False


class TestConstruction:
    def test_constructed_without_bus_service(self) -> None:
        """EventFilter is constructable with plain config values — no BusService dependency."""
        ef = EventFilter(
            excluded_domains=("media_player", "sensor.*"),
            excluded_entities=("light.kitchen",),
            logger=make_logger(),
        )
        assert "media_player" in ef._excluded_domains_exact
        assert "sensor.*" in ef._excluded_domain_globs
        assert "light.kitchen" in ef._excluded_entities_exact
        assert ef._has_exclusions is True

    def test_none_config_values_produce_no_exclusions(self) -> None:
        """None config values result in _has_exclusions=False."""
        ef = make_filter(excluded_domains=None, excluded_entities=None)
        assert ef._has_exclusions is False

    def test_empty_tuples_produce_no_exclusions(self) -> None:
        """Empty tuples result in _has_exclusions=False."""
        ef = make_filter(excluded_domains=(), excluded_entities=())
        assert ef._has_exclusions is False
