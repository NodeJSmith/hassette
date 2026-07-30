"""Tests for topic-derived priority tier classification (#671, backpressure epic #72).

``classify_topic`` supplies the default tier for any listener that does not pass an explicit
``event_priority=``. These tests pin the classification table and the ranking that dispatch
ordering depends on.
"""

import pytest

from hassette.bus.priority import LOW_CHURN_STATE_DOMAINS, TOPIC_PRIORITIES, classify_topic
from hassette.types.enums import EventPriority, Topic


class TestEventPriorityRank:
    def test_ranks_are_strictly_ordered(self) -> None:
        """Critical > high > normal > low, the order dispatch hands out slots in."""
        assert (
            EventPriority.CRITICAL.rank > EventPriority.HIGH.rank > EventPriority.NORMAL.rank > EventPriority.LOW.rank
        )

    def test_every_member_has_a_rank(self) -> None:
        """A new tier added without a rank entry would raise here, not at dispatch time."""
        for priority in EventPriority:
            assert isinstance(priority.rank, int)

    def test_members_are_plain_strings(self) -> None:
        """Tiers serialize as their lowercase names for config, JSON, and the DB CHECK constraint."""
        assert EventPriority.LOW == "low"
        assert EventPriority.CRITICAL == "critical"


class TestClassifyTopic:
    def test_unknown_topic_is_normal(self) -> None:
        """An unrecognized topic is never shed under load — it defaults to normal."""
        assert classify_topic("my_app.custom_thing") is EventPriority.NORMAL

    def test_bare_state_changed_topic_is_normal(self) -> None:
        """The unexpanded state-change topic (what StateProxy subscribes to) is not a domain route."""
        assert classify_topic(str(Topic.HASS_EVENT_STATE_CHANGED)) is EventPriority.NORMAL

    @pytest.mark.parametrize(
        "topic",
        [
            "hass.event.state_changed.sensor.living_room_power",
            "hass.event.state_changed.sensor.*",
        ],
    )
    def test_sensor_state_routes_are_low(self, topic: str) -> None:
        """Both the entity route and the domain glob classify by domain."""
        assert classify_topic(topic) is EventPriority.LOW

    @pytest.mark.parametrize(
        "topic",
        [
            "hass.event.state_changed.light.office",
            "hass.event.state_changed.binary_sensor.front_door",
            "hass.event.state_changed.lock.*",
        ],
    )
    def test_non_low_churn_state_routes_are_normal(self, topic: str) -> None:
        """binary_sensor is deliberately not low — its events are edge-triggered."""
        assert classify_topic(topic) is EventPriority.NORMAL

    def test_call_service_is_high(self) -> None:
        assert classify_topic(str(Topic.HASS_EVENT_CALL_SERVICE)) is EventPriority.HIGH

    def test_service_status_is_critical(self) -> None:
        assert classify_topic(str(Topic.HASSETTE_EVENT_SERVICE_STATUS)) is EventPriority.CRITICAL

    def test_execution_completed_is_low(self) -> None:
        """One event per handler execution, so it scales with the load that saturates dispatch."""
        assert classify_topic(str(Topic.HASSETTE_EVENT_EXECUTION_COMPLETED)) is EventPriority.LOW

    def test_table_keys_are_real_topics(self) -> None:
        """A typo'd or renamed Topic in the table would silently never match a real listener."""
        known = {str(topic) for topic in Topic}
        assert {str(key) for key in TOPIC_PRIORITIES} <= known

    def test_low_churn_domains_do_not_include_binary_sensor(self) -> None:
        """Guards the deliberate exclusion documented on LOW_CHURN_STATE_DOMAINS."""
        assert "binary_sensor" not in LOW_CHURN_STATE_DOMAINS
