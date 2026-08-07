"""Unit tests for DomainStates membership filtering.

Pins the ``Mapping`` invariant this task fixes: ``__iter__``, ``__len__``, ``__contains__``, and
``__getitem__`` must all agree on membership (predicate AND convertibility) — see
``design/specs/093-sensor-device-class-subtypes/design.md`` "## Architecture -> Filtering in
DomainStates". Before this change, a naive filtered view could report ``len() == 5`` while
``list()`` yielded 2 sensors, because ``__len__`` consulted the state proxy's raw domain count
instead of running the same predicate+conversion check as ``__iter__``.
"""

import logging

import pytest

from hassette.events import HassStateDict
from hassette.exceptions import EntityNotInViewError
from hassette.models.states import LightState, SensorState
from hassette.models.states.sensor_shapes import NumericSensorState, SensorShape, classify_sensor_shape
from hassette.state_manager import DomainStates
from hassette.test_utils import FakeStateReader, make_sensor_state_dict


def numeric_shape_predicate(state: HassStateDict) -> bool:
    """Membership predicate matching NumericSensorState — mirrors what a real accessor builds."""
    return classify_sensor_shape(state.get("attributes", {})) == SensorShape.NUMERIC


def build_multi_shape_sensor_fixture() -> FakeStateReader:
    """A fixture proxy spanning all four sensor shapes, an unmatched sensor, and a numeric-metadata
    sensor whose value fails conversion — the case a naive implementation gets wrong.
    """
    states: dict[str, HassStateDict] = {
        "sensor.temperature": make_sensor_state_dict(
            "sensor.temperature", "21.5", unit_of_measurement="°C", device_class="temperature"
        ),
        "sensor.co2": make_sensor_state_dict(
            "sensor.co2", "415", unit_of_measurement="ppm", device_class="carbon_dioxide"
        ),
        "sensor.mode": make_sensor_state_dict("sensor.mode", "cool", device_class="enum", options=["cool", "heat"]),
        "sensor.last_motion": make_sensor_state_dict(
            "sensor.last_motion", "2024-01-01T00:00:00+00:00", device_class="timestamp"
        ),
        "sensor.expiry": make_sensor_state_dict("sensor.expiry", "2024-01-01", device_class="date"),
        "sensor.garbage": make_sensor_state_dict(
            "sensor.garbage", "not-a-number", unit_of_measurement="°C", device_class="temperature"
        ),
        "sensor.no_metadata": make_sensor_state_dict("sensor.no_metadata", "some text"),
    }
    return FakeStateReader(states)


def build_numeric_domain_states() -> DomainStates[NumericSensorState]:
    """A DomainStates view narrowed to NumericSensorState over the multi-shape fixture.

    NumericSensorState does not re-declare `domain` (see sensor_shapes.py), so `get_domain()`
    would raise `NoDomainAnnotationError` — the explicit `domain="sensor"` constructor parameter
    is what makes this construction possible at all. A real accessor over this shape is built the
    same way, plus a membership predicate wrapping `classify_sensor_shape`.
    """
    reader = build_multi_shape_sensor_fixture()
    return DomainStates(reader, NumericSensorState, domain="sensor", predicate=numeric_shape_predicate)


class TestMappingInvariant:
    """Membership is predicate AND convertibility, agreeing across all four Mapping methods."""

    def test_len_equals_len_of_list(self) -> None:
        """The pin: len(ds) must equal len(list(ds)) even with unmatched and unconvertible entities."""
        ds = build_numeric_domain_states()

        assert len(ds) == len(list(ds))

    def test_only_matching_and_convertible_entities_are_members(self) -> None:
        ds = build_numeric_domain_states()

        member_ids = set(ds)

        assert member_ids == {"sensor.temperature", "sensor.co2"}

    def test_wrong_shape_entities_are_excluded(self) -> None:
        """A sensor whose shape doesn't match the predicate is excluded, even though it exists."""
        ds = build_numeric_domain_states()

        assert "sensor.mode" not in ds
        assert "sensor.last_motion" not in ds
        assert "sensor.expiry" not in ds

    def test_numeric_metadata_with_unconvertible_value_is_excluded(self) -> None:
        """The naive-implementation trap: predicate says numeric, but the value fails conversion.

        Excluded from membership everywhere, not just from iteration — this is what keeps
        len(m) == len(list(m)) unconditional (design.md Edge Cases).
        """
        ds = build_numeric_domain_states()

        assert "sensor.garbage" not in ds
        assert "sensor.garbage" not in set(ds)
        assert len(ds) == len(list(ds))

    def test_no_metadata_entity_is_excluded(self) -> None:
        ds = build_numeric_domain_states()

        assert "sensor.no_metadata" not in ds

    def test_contains_agrees_with_iteration_for_every_entity(self) -> None:
        ds = build_numeric_domain_states()
        member_ids = set(ds)

        for entity_id in [
            "sensor.temperature",
            "sensor.co2",
            "sensor.mode",
            "sensor.last_motion",
            "sensor.expiry",
            "sensor.garbage",
            "sensor.no_metadata",
        ]:
            assert (entity_id in ds) == (entity_id in member_ids)

    def test_items_and_values_only_contain_members(self) -> None:
        ds = build_numeric_domain_states()

        items = dict(ds.items())
        assert set(items) == {"sensor.temperature", "sensor.co2"}
        for state in ds.values():
            assert isinstance(state, NumericSensorState)
            assert state.value is not None


class TestEntityNotInViewError:
    """Direct lookup of a non-member raises EntityNotInViewError, a KeyError subclass."""

    def test_wrong_shape_lookup_raises_entity_not_in_view_error(self) -> None:
        ds = build_numeric_domain_states()

        with pytest.raises(EntityNotInViewError) as exc_info:
            ds["sensor.mode"]

        err = exc_info.value
        assert err.entity_id == "sensor.mode"
        assert err.device_class == "enum"
        assert err.state_class is NumericSensorState

    def test_entity_not_in_view_error_is_a_key_error(self) -> None:
        ds = build_numeric_domain_states()

        with pytest.raises(KeyError):
            ds["sensor.mode"]

        assert issubclass(EntityNotInViewError, KeyError)

    def test_unconvertible_numeric_metadata_lookup_raises_entity_not_in_view_error(self) -> None:
        """Predicate passes (metadata says numeric) but conversion fails — still EntityNotInViewError,
        not a raw conversion error, so the Mapping invariant holds for direct lookup too.
        """
        ds = build_numeric_domain_states()

        with pytest.raises(EntityNotInViewError) as exc_info:
            ds["sensor.garbage"]

        assert exc_info.value.entity_id == "sensor.garbage"
        assert exc_info.value.__cause__ is not None

    def test_get_returns_none_for_non_member(self) -> None:
        """.get() relies on Mapping's KeyError-catching default implementation."""
        ds = build_numeric_domain_states()

        assert ds.get("sensor.mode") is None
        assert ds.get("sensor.garbage") is None

    def test_iteration_omits_non_member(self) -> None:
        ds = build_numeric_domain_states()

        assert "sensor.mode" not in list(ds)
        assert "sensor.garbage" not in list(ds)

    def test_entity_missing_from_domain_entirely_raises_plain_key_error(self) -> None:
        """An entity absent from the domain altogether keeps raising a plain KeyError,
        distinct from EntityNotInViewError (which covers entities present but excluded).
        """
        ds = build_numeric_domain_states()

        with pytest.raises(KeyError) as exc_info:
            ds["sensor.does_not_exist"]

        assert not isinstance(exc_info.value, EntityNotInViewError)

    def test_default_predicate_none_keeps_raising_underlying_conversion_error(self) -> None:
        """No predicate set (today's behavior) — a conversion failure propagates as-is, not wrapped
        in EntityNotInViewError. Backward-compat guarantee for existing, unfiltered DomainStates use.
        """
        reader = build_multi_shape_sensor_fixture()
        ds: DomainStates[NumericSensorState] = DomainStates(reader, NumericSensorState, domain="sensor")

        with pytest.raises(Exception) as exc_info:  # noqa: PT011 — asserting NOT EntityNotInViewError below
            ds["sensor.garbage"]

        assert not isinstance(exc_info.value, EntityNotInViewError)


class TestNoErrorLogsOnSkip:
    """Iterating a narrowed view emits no ERROR records for non-matching entities.

    "Non-matching" here means excluded by the membership predicate (wrong shape) — the routine,
    expected case for a filtered view. This is the scenario the debug-level skip log is meant for:
    a 200-sensor install iterating a numeric-only view would otherwise emit roughly 150 error
    lines for every non-numeric sensor. Predicate filtering resolves most of that volume outright:
    entities excluded by the predicate never reach conversion at all, so nothing logs for them, at
    any level.

    The one entity excluded by *conversion failure* (`sensor.garbage`, predicate-passing but
    unconvertible) is deliberately tested separately below: `DomainStates`'s own skip-path log for
    that case drops to debug, but the shared conversion pipeline
    (`StateRegistry.conversion_with_error_handling`, `conversion/state_registry.py:203`) logs an
    unconditional ERROR on every conversion failure across the whole framework, independent of and
    predating this feature. Silencing that is out of scope here — it is not among this change's
    target files and touches every conversion failure, not just filtered-view membership checks.
    """

    def test_predicate_only_exclusions_emit_no_records_at_all(self, caplog: pytest.LogCaptureFixture) -> None:
        """Entities excluded purely by shape mismatch never reach conversion, so nothing logs."""
        reader = build_multi_shape_sensor_fixture()
        # Predicate-mismatch entities only — no conversion is attempted for these, so no log
        # should be emitted at any level, not just no ERROR.
        non_matching_ids = {"sensor.mode", "sensor.last_motion", "sensor.expiry", "sensor.no_metadata"}
        ds: DomainStates[NumericSensorState] = DomainStates(
            reader, NumericSensorState, domain="sensor", predicate=numeric_shape_predicate
        )

        with caplog.at_level(logging.DEBUG, logger="hassette"):
            for entity_id in non_matching_ids:
                assert entity_id not in ds

        assert caplog.records == []

    def test_unconvertible_entity_skip_is_logged_at_debug_not_error_by_domain_states(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """DomainStates' own skip-path log for a conversion failure is debug, not error."""
        ds = build_numeric_domain_states()

        # A test earlier in suite order may have left propagate=False on the "hassette" logger
        # via enable_basic_logging() (src/hassette/logging_.py:442); caplog's handler sits on the
        # root logger, so without this the child logger's records never reach it. Same workaround
        # as tests/unit/web/test_middleware.py and tests/unit/core/conftest.py.
        logging.getLogger("hassette").propagate = True

        with caplog.at_level(logging.DEBUG, logger="hassette.state_manager.state_manager"):
            list(ds)

        state_manager_records = [r for r in caplog.records if r.name == "hassette.state_manager.state_manager"]
        assert all(r.levelno < logging.ERROR for r in state_manager_records)
        assert any(r.levelno == logging.DEBUG and "sensor.garbage" in r.getMessage() for r in state_manager_records)


class TestBackwardCompatibleConstruction:
    """Existing 2-positional-arg call sites (`DomainStates(proxy, Model)`) must keep working."""

    def test_domain_defaults_to_model_get_domain(self) -> None:
        reader = FakeStateReader({})
        ds = DomainStates(reader, LightState)

        assert ds._domain == "light"

    def test_predicate_defaults_to_none_and_accepts_everything_in_domain(self) -> None:
        reader = build_multi_shape_sensor_fixture()
        ds: DomainStates[SensorState] = DomainStates(reader, SensorState, domain="sensor")

        # Every entity in the domain is a candidate member when no predicate is set — the only
        # exclusion left is convertibility. SensorState.value is `str | None`, so every fixture
        # entity (including the "garbage" one, since any string is a valid str value) converts.
        assert set(ds) == set(build_multi_shape_sensor_fixture().states)
