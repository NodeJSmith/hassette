"""Integration tests for the four narrowed sensor-shape StateManager accessors.

Each of `numeric_sensor`, `enum_sensor`, `timestamp_sensor`, and `date_sensor` reaches through
`StateManager` to a real state proxy, which is the seam where the domain-passing and caching
changes in `_domain_states_for` could regress. Unit-level membership and the `Mapping`
invariant across `__iter__`/`__len__`/`__contains__`/`__getitem__` are already pinned in
`tests/unit/state_manager/test_domain_states_membership.py`; this file proves the same
invariants hold end-to-end through the accessor properties themselves.

See `design/specs/093-sensor-device-class-subtypes/design.md` "## Architecture -> The
accessors" and the `self.states[NumericSensorState]` Edge Cases entry.
"""

from typing import TYPE_CHECKING

from hassette.models.states import (
    DateSensorState,
    EnumSensorState,
    NumericSensorState,
    TimestampSensorState,
)
from hassette.state_manager import DomainStates, StateManager
from hassette.testing import make_full_state_change_event, make_sensor_state_dict, wait_for
from tests.support.harness import send_and_wait

if TYPE_CHECKING:
    from hassette.testing import HassetteHarness


class TestSensorShapeAccessorsReturnMatchingClass:
    """Each accessor returns a DomainStates parameterized to its matching class."""

    async def test_numeric_sensor(self, seeded_sensor_state_manager: StateManager) -> None:
        numeric = seeded_sensor_state_manager.numeric_sensor

        assert isinstance(numeric, DomainStates)
        assert set(numeric) == {"sensor.temperature"}
        for state in numeric.values():
            assert isinstance(state, NumericSensorState)
            assert isinstance(state.value, float)

    async def test_enum_sensor(self, seeded_sensor_state_manager: StateManager) -> None:
        enum_sensors = seeded_sensor_state_manager.enum_sensor

        assert isinstance(enum_sensors, DomainStates)
        assert set(enum_sensors) == {"sensor.mode"}
        for state in enum_sensors.values():
            assert isinstance(state, EnumSensorState)
            assert state.value == "cool"

    async def test_timestamp_sensor(self, seeded_sensor_state_manager: StateManager) -> None:
        timestamp_sensors = seeded_sensor_state_manager.timestamp_sensor

        assert isinstance(timestamp_sensors, DomainStates)
        assert set(timestamp_sensors) == {"sensor.last_motion", "sensor.uptime"}
        for state in timestamp_sensors.values():
            assert isinstance(state, TimestampSensorState)

    async def test_date_sensor(self, seeded_sensor_state_manager: StateManager) -> None:
        date_sensors = seeded_sensor_state_manager.date_sensor

        assert isinstance(date_sensors, DomainStates)
        assert set(date_sensors) == {"sensor.expiry"}
        for state in date_sensors.values():
            assert isinstance(state, DateSensorState)

    async def test_uptime_sensor_appears_in_timestamp_sensor_accessor(
        self, seeded_sensor_state_manager: StateManager
    ) -> None:
        """The accessor-level uptime assertion — the classifier-level half lives in the unit
        tests for `classify_sensor_shape`.
        """
        assert "sensor.uptime" in seeded_sensor_state_manager.timestamp_sensor
        uptime_state = seeded_sensor_state_manager.timestamp_sensor["sensor.uptime"]
        assert isinstance(uptime_state, TimestampSensorState)


class TestSensorShapeAccessorMembership:
    """Membership is exactly the sensors whose shape matches AND whose state converts."""

    async def test_unknown_shape_sensor_excluded_from_every_narrowed_accessor(
        self, seeded_sensor_state_manager: StateManager
    ) -> None:
        assert "sensor.no_metadata" not in seeded_sensor_state_manager.numeric_sensor
        assert "sensor.no_metadata" not in seeded_sensor_state_manager.enum_sensor
        assert "sensor.no_metadata" not in seeded_sensor_state_manager.timestamp_sensor
        assert "sensor.no_metadata" not in seeded_sensor_state_manager.date_sensor
        # Still reachable through the untouched, unfiltered `sensor` accessor.
        assert "sensor.no_metadata" in seeded_sensor_state_manager.sensor

    async def test_unconvertible_numeric_metadata_sensor_excluded_everywhere(
        self, seeded_sensor_state_manager: StateManager
    ) -> None:
        """Predicate says numeric (has unit + device_class) but the value doesn't parse — excluded
        from membership everywhere, keeping len(m) == len(list(m)) unconditional.
        """
        numeric = seeded_sensor_state_manager.numeric_sensor

        assert "sensor.garbage" not in numeric
        assert "sensor.garbage" not in set(numeric)
        assert len(numeric) == len(list(numeric))

    async def test_sensor_accessor_still_contains_every_sensor(self, seeded_sensor_state_manager: StateManager) -> None:
        """The existing, unfiltered `sensor` accessor is untouched by the narrowed views."""
        assert set(seeded_sensor_state_manager.sensor) == {
            "sensor.temperature",
            "sensor.mode",
            "sensor.last_motion",
            "sensor.uptime",
            "sensor.expiry",
            "sensor.garbage",
            "sensor.no_metadata",
        }


class TestSensorShapeAccessorCaching:
    """Each accessor caches independently — the four classes are distinct keys in the existing
    per-class `_domain_states_cache`, so accessing one does not disturb another (design.md
    "## Architecture -> The accessors").
    """

    async def test_repeated_access_returns_the_same_cached_instance(self, state_manager: StateManager) -> None:
        assert state_manager.numeric_sensor is state_manager.numeric_sensor

    async def test_accessors_do_not_share_a_cache_entry(self, state_manager: StateManager) -> None:
        assert state_manager.numeric_sensor is not state_manager.enum_sensor
        assert state_manager.numeric_sensor is not state_manager.timestamp_sensor
        assert state_manager.numeric_sensor is not state_manager.date_sensor
        # The pre-existing `sensor` accessor keeps its own cache entry too.
        assert state_manager.sensor is not state_manager.numeric_sensor


class TestSensorShapeAccessorRuntimeDeviceClassChange:
    """Membership is recomputed per access, never cached across a device_class change — a
    device_class flip correctly moves an entity between narrowed views on the next access
    (design.md Edge Cases, "device_class changes at runtime").
    """

    async def test_device_class_flip_moves_entity_between_shape_accessors(
        self, hassette_with_state_proxy: "HassetteHarness", state_manager: StateManager
    ) -> None:
        hassette = hassette_with_state_proxy

        temperature_dict = make_sensor_state_dict(
            "sensor.flexible", "21.5", unit_of_measurement="°C", device_class="temperature"
        )
        await send_and_wait(hassette, "sensor.flexible", None, temperature_dict)

        assert "sensor.flexible" in state_manager.numeric_sensor
        assert "sensor.flexible" not in state_manager.enum_sensor

        enum_dict = make_sensor_state_dict("sensor.flexible", "cool", device_class="enum", options=["cool", "heat"])
        event = make_full_state_change_event("sensor.flexible", temperature_dict, enum_dict)
        await hassette.send_event(event)
        await wait_for(
            lambda: (
                (hassette.state_proxy.get_state("sensor.flexible") or {}).get("attributes", {}).get("device_class")
                == "enum"
            ),
            desc="sensor.flexible device_class flipped to enum",
        )

        # Same DomainStates instances (cached per class) — membership is recomputed per access,
        # not cached across the change.
        assert "sensor.flexible" not in state_manager.numeric_sensor
        assert "sensor.flexible" in state_manager.enum_sensor
