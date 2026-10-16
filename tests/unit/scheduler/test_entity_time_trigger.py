"""Tests for the EntityTime trigger and the state-value parsing it relies on.

Covers value parsing (parse_entity_time), resolution against a bound state reader,
the WAITING parking behaviour for entities with no usable time, daily rollover,
and the telemetry/dedup metadata methods.
"""

import re
from typing import TYPE_CHECKING, Any

import pytest
from whenever import TimeDelta, ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.scheduler.triggers import WAITING, EntityTime, parse_entity_time
from hassette.types import TriggerProtocol

from .conftest import TZ, zdt

if TYPE_CHECKING:
    from hassette.events import HassStateDict

ENTITY_ID = "sensor.phone_next_alarm"


def make_reader(states: dict[str, Any]):
    """Return a state reader over a plain dict, matching BusService.read_entity_state."""

    def reader(entity_id: str) -> "HassStateDict | None":
        return states.get(entity_id)

    return reader


def bound_trigger(
    state: Any = None,
    *,
    attributes: dict[str, Any] | None = None,
    present: bool = True,
    **kwargs: Any,
) -> EntityTime:
    """Build an EntityTime bound to a single-entity state reader."""
    states: dict[str, Any] = {}
    if present:
        states[ENTITY_ID] = {"entity_id": ENTITY_ID, "state": state, "attributes": attributes or {}}
    trigger = EntityTime(ENTITY_ID, **kwargs)
    trigger.bind_state_reader(make_reader(states))
    return trigger


@pytest.fixture(autouse=True)
def configured_timezone():
    """Pin the process timezone so naive and time-only values parse deterministically."""
    previous = date_utils._configured_tz
    date_utils.configure(TZ)
    yield
    date_utils.configure(previous)


class TestParseEntityTime:
    def test_offset_aware_iso_string(self) -> None:
        """An offset-aware ISO string — what most HA sensors report — parses to that instant."""
        assert parse_entity_time("2026-07-28T07:00:00-05:00") == zdt(2026, 7, 28, 7, 0)

    def test_naive_iso_string_uses_configured_timezone(self) -> None:
        """A naive date-time, as input_datetime stores it, is read in the configured timezone."""
        assert parse_entity_time("2026-07-28 07:00:00") == zdt(2026, 7, 28, 7, 0)

    def test_time_only_string_resolves_against_today(self) -> None:
        """A time-only value resolves against today's date in the configured timezone."""
        today = date_utils.now()
        parsed = parse_entity_time("07:00:00")
        assert parsed is not None
        assert (parsed.year, parsed.month, parsed.day) == (today.year, today.month, today.day)
        assert (parsed.hour, parsed.minute) == (7, 0)

    def test_unix_timestamp(self) -> None:
        """A numeric value is a unix timestamp, as on input_datetime's `timestamp` attribute."""
        expected = zdt(2026, 7, 28, 7, 0)
        assert parse_entity_time(expected.timestamp()) == expected

    def test_zoned_datetime_passes_through(self) -> None:
        """An already-parsed ZonedDateTime is returned unchanged."""
        value = zdt(2026, 7, 28, 7, 0)
        assert parse_entity_time(value) is value

    @pytest.mark.parametrize("value", ["unknown", "unavailable", "", "   ", "none", "UNAVAILABLE"])
    def test_unusable_state_strings_return_none(self, value: str) -> None:
        """States that carry no time — unavailable, unknown, empty — resolve to None."""
        assert parse_entity_time(value) is None

    @pytest.mark.parametrize("value", [None, True, False, ["07:00"], {"at": "07:00"}])
    def test_non_time_values_return_none(self, value: Any) -> None:
        """Values that are not times (including bools, which are ints) resolve to None."""
        assert parse_entity_time(value) is None

    def test_unparsable_string_returns_none(self) -> None:
        """A string in no recognised time format resolves to None rather than raising."""
        assert parse_entity_time("not a time at all") is None


class TestEntityTimeConstruction:
    def test_invalid_entity_id_raises(self) -> None:
        """An entity_id without a domain is rejected at construction."""
        with pytest.raises(ValueError, match=re.escape("must be '<domain>.<object_id>'")):
            EntityTime("phone_next_alarm")

    def test_defaults(self) -> None:
        """Offset defaults to zero, attribute to None, daily to False."""
        trigger = EntityTime(ENTITY_ID)
        assert trigger.offset == TimeDelta()
        assert trigger.attribute is None
        assert trigger.daily is False


class TestEntityTimeResolve:
    def test_unbound_trigger_resolves_to_waiting(self) -> None:
        """A trigger used outside the scheduler has no state source and never fires."""
        trigger = EntityTime(ENTITY_ID)
        assert trigger.resolve(zdt(2026, 7, 28, 6, 0)) is WAITING

    def test_missing_entity_resolves_to_waiting(self) -> None:
        """An entity absent from the state cache resolves to WAITING."""
        trigger = bound_trigger(present=False)
        assert trigger.resolve(zdt(2026, 7, 28, 6, 0)) is WAITING

    def test_future_time_resolves_to_that_time(self) -> None:
        """A future alarm time is the fire time."""
        trigger = bound_trigger("2026-07-28T07:00:00-05:00")
        assert trigger.resolve(zdt(2026, 7, 28, 6, 0)) == zdt(2026, 7, 28, 7, 0)

    def test_past_time_resolves_to_waiting(self) -> None:
        """An alarm time that has already passed leaves nothing to schedule."""
        trigger = bound_trigger("2026-07-28T07:00:00-05:00")
        assert trigger.resolve(zdt(2026, 7, 28, 8, 0)) is WAITING

    def test_negative_offset_fires_early(self) -> None:
        """A negative offset moves the fire time before the entity's time."""
        trigger = bound_trigger("2026-07-28T07:00:00-05:00", offset=TimeDelta(minutes=-30))
        assert trigger.resolve(zdt(2026, 7, 28, 6, 0)) == zdt(2026, 7, 28, 6, 30)

    def test_positive_offset_fires_late(self) -> None:
        """A positive offset moves the fire time after the entity's time."""
        trigger = bound_trigger("2026-07-28T07:00:00-05:00", offset=TimeDelta(minutes=15))
        assert trigger.resolve(zdt(2026, 7, 28, 6, 0)) == zdt(2026, 7, 28, 7, 15)

    def test_attribute_is_read_instead_of_state(self) -> None:
        """attribute= reads the time from an attribute, as on sun.sun."""
        trigger = bound_trigger(
            "above_horizon",
            attributes={"next_dawn": "2026-07-28T05:45:00-05:00"},
            attribute="next_dawn",
        )
        assert trigger.resolve(zdt(2026, 7, 28, 4, 0)) == zdt(2026, 7, 28, 5, 45)

    def test_missing_attribute_resolves_to_waiting(self) -> None:
        """An attribute the entity does not expose resolves to WAITING."""
        trigger = bound_trigger("above_horizon", attribute="next_dawn")
        assert trigger.resolve(zdt(2026, 7, 28, 4, 0)) is WAITING


class TestEntityTimeDaily:
    def test_daily_fires_today_when_time_is_ahead(self) -> None:
        """Daily mode keeps only the time of day and fires at today's occurrence."""
        trigger = bound_trigger("2026-01-05T07:00:00-06:00", daily=True)
        assert trigger.resolve(zdt(2026, 7, 28, 6, 0)) == zdt(2026, 7, 28, 7, 0)

    def test_daily_rolls_over_when_time_has_passed(self) -> None:
        """Once today's occurrence has passed, daily mode fires tomorrow."""
        trigger = bound_trigger("2026-01-05T07:00:00-06:00", daily=True)
        assert trigger.resolve(zdt(2026, 7, 28, 8, 0)) == zdt(2026, 7, 29, 7, 0)

    def test_daily_applies_offset_before_extracting_time_of_day(self) -> None:
        """The offset shifts the wall-clock time the daily schedule repeats at."""
        trigger = bound_trigger("2026-01-05T07:00:00-06:00", offset=TimeDelta(minutes=-30), daily=True)
        assert trigger.resolve(zdt(2026, 7, 28, 6, 0)) == zdt(2026, 7, 28, 6, 30)

    def test_daily_next_run_after_firing_is_tomorrow(self) -> None:
        """next_run_time after today's fire returns tomorrow's occurrence."""
        trigger = bound_trigger("2026-01-05T07:00:00-06:00", daily=True)
        previous = zdt(2026, 7, 28, 7, 0)
        assert trigger.next_run_time(previous, zdt(2026, 7, 28, 7, 0, 1)) == zdt(2026, 7, 29, 7, 0)


class TestEntityTimeParking:
    def test_first_run_time_parks_when_unresolvable(self) -> None:
        """An unavailable entity parks the job instead of failing registration."""
        trigger = bound_trigger("unavailable")
        assert trigger.first_run_time(zdt(2026, 7, 28, 6, 0)) is WAITING

    def test_next_run_time_parks_instead_of_returning_none(self) -> None:
        """Returning None would remove the job; the entity must be able to schedule it again."""
        trigger = bound_trigger("2026-07-28T07:00:00-05:00")
        result = trigger.next_run_time(zdt(2026, 7, 28, 7, 0), zdt(2026, 7, 28, 7, 0, 1))
        assert result is WAITING

    def test_parked_trigger_recovers_when_entity_reports_a_time(self) -> None:
        """A parked trigger returns a real time as soon as the entity has one."""
        states: dict[str, Any] = {ENTITY_ID: {"entity_id": ENTITY_ID, "state": "unavailable", "attributes": {}}}
        trigger = EntityTime(ENTITY_ID)
        trigger.bind_state_reader(make_reader(states))
        now = zdt(2026, 7, 28, 6, 0)
        assert trigger.first_run_time(now) is WAITING

        states[ENTITY_ID] = {
            "entity_id": ENTITY_ID,
            "state": "2026-07-28T07:00:00-05:00",
            "attributes": {},
        }
        assert trigger.first_run_time(now) == zdt(2026, 7, 28, 7, 0)


class TestEntityTimeMetadata:
    def test_label_is_not_a_reserved_builtin_name(self) -> None:
        """Custom triggers must not claim a built-in trigger label."""
        assert EntityTime(ENTITY_ID).trigger_label() == "entity_time"

    def test_db_type_is_custom(self) -> None:
        """EntityTime is not one of the DB's built-in trigger types."""
        assert EntityTime(ENTITY_ID).trigger_db_type() == "custom"

    def test_detail_names_entity_attribute_offset_and_mode(self) -> None:
        """The detail string carries everything that distinguishes one EntityTime from another."""
        trigger = EntityTime(ENTITY_ID, attribute="next_dawn", offset=TimeDelta(minutes=-30), daily=True)
        assert trigger.trigger_detail() == f"{ENTITY_ID}.next_dawn -1800s daily"

    def test_detail_omits_zero_offset(self) -> None:
        """A zero offset is left out of the detail string."""
        assert EntityTime(ENTITY_ID).trigger_detail() == ENTITY_ID

    def test_trigger_id_differs_per_configuration(self) -> None:
        """if_exists='skip' dedup relies on configuration differences changing trigger_id."""
        base = EntityTime(ENTITY_ID).trigger_id()
        assert EntityTime(ENTITY_ID).trigger_id() == base
        assert EntityTime(ENTITY_ID, daily=True).trigger_id() != base
        assert EntityTime(ENTITY_ID, offset=TimeDelta(minutes=5)).trigger_id() != base
        assert EntityTime(ENTITY_ID, attribute="next_dawn").trigger_id() != base
        assert EntityTime("sensor.other_alarm").trigger_id() != base

    def test_repr_includes_detail(self) -> None:
        """Repr is used in scheduler error messages, so it must name the entity."""
        assert repr(EntityTime(ENTITY_ID)) == f"EntityTime({ENTITY_ID})"


def test_trigger_satisfies_protocol() -> None:
    """Scheduler.schedule() rejects anything that is not a TriggerProtocol."""
    assert isinstance(EntityTime(ENTITY_ID), TriggerProtocol)


def test_resolve_rounds_to_whole_seconds() -> None:
    """Fire times are second-aligned, matching every other trigger."""
    trigger = bound_trigger("2026-07-28T07:00:00.750-05:00")
    resolved = trigger.resolve(zdt(2026, 7, 28, 6, 0))
    assert resolved == ZonedDateTime(2026, 7, 28, 7, 0, 1, tz=TZ)
