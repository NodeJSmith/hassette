"""Tests for the four narrowed sensor shape classes and the shape classifier.

Covers per-class value typing and construction from a state dict for `NumericSensorState`,
`EnumSensorState`, `TimestampSensorState`, and `DateSensorState`, plus the shape classifier
that decides between them (or "unknown"). The assertion that the four classes must not
register in the state catalog lives in tests/unit/models/test_state_catalog.py instead,
alongside the other catalog-registration tests it already covers.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from whenever import Date, ZonedDateTime

from hassette.conversion.state_registry import convert_state_dict_to_model
from hassette.models.states.sensor import SensorState
from hassette.models.states.sensor_shapes import (
    DateSensorState,
    EnumSensorState,
    NumericSensorState,
    SensorShape,
    TimestampSensorState,
    classify_sensor_shape,
)
from hassette.test_utils.helpers import make_sensor_state_dict

WORKTREE_ROOT = Path(__file__).resolve().parents[3]
PYRIGHT_PROBE_DIR = WORKTREE_ROOT / "tests" / "pyright_probes" / "sensor_shape_probe"
PYRIGHT_PROBE_FILE = PYRIGHT_PROBE_DIR / "narrowing_probe.py"
PYRIGHT_PROBE_TIMEOUT_SECONDS = 120

# Attribute combinations pulled from a live 270-sensor Home Assistant instance (the same
# population design.md's precision/recall figures were measured against — 46% of sensors
# carry no `device_class` at all) via the `home-assistant` MCP tools, keeping only the
# three attribute keys that drive classification (`device_class`, `state_class`,
# `unit_of_measurement`). Seven of the nine cases below are real entities from that instance;
# their attributes are quoted verbatim and their source entity is a generic
# integration/appliance name with no household, person, or device-owner information (e.g.
# `sensor.uptime`, `sensor.washer_detergent_level`, `sensor.garage_door_numeric_state`) so no
# anonymization was needed. Two cases (marked SYNTHETIC below) have no real example anywhere
# in the instance — confirmed by a full sweep of all 270 sensor entities in the instance,
# spanning every integration present (weather, mobile-app companion, appliances, Z-Wave,
# Zigbee2MQTT, vacuum, backup, budget tracking, YouTube stats, calendar/appointments,
# cameras) — and are hand-authored instead; see each case's comment for why.
CLASSIFIER_FIXTURE: list[tuple[str, dict[str, Any], SensorShape]] = [
    (
        # REAL — sensor.openweathermap_temperature
        "numeric_with_device_class",
        {"device_class": "temperature", "unit_of_measurement": "°F", "state_class": "measurement"},
        SensorShape.NUMERIC,
    ),
    (
        # REAL — sensor.garage_door_numeric_state (state "3"; no device_class or
        # unit_of_measurement, isolates the `state_class`-only branch of
        # `_numeric_state_expected`)
        "numeric_no_device_class_but_state_class",
        {"state_class": "measurement"},
        SensorShape.NUMERIC,
    ),
    (
        # REAL — sensor.ratgdo_openings (a garage-door opener's lifetime open count; unit
        # "openings", no device_class or state_class)
        "numeric_no_device_class_but_unit",
        {"unit_of_measurement": "openings"},
        SensorShape.NUMERIC,
    ),
    (
        # REAL — sensor.big_air_purifier_air_quality (state "excellent"; no device_class,
        # state_class, or unit_of_measurement at all)
        "no_metadata_at_all",
        {},
        SensorShape.UNKNOWN,
    ),
    (
        # SYNTHETIC — every device_class observed across the checked entities was either
        # absent or a value HA's own DEVICE_CLASS enum recognizes (temperature, enum,
        # timestamp, uptime, duration, monetary, signal_strength, distance, wind_direction,
        # battery, ...); no entity in this instance carries an unrecognized/custom string.
        "custom_device_class_no_other_metadata",
        {"device_class": "third_party_widget_status"},
        SensorShape.UNKNOWN,
    ),
    (
        # SYNTHETIC — no entity in this instance carries device_class "date". Every
        # calendar-like sensor found (next alarm, next scheduled backup, appointment time)
        # uses "timestamp" instead, which is consistent with "date" being genuinely rare in
        # real installs, not a search miss — checked every appointment/alarm/backup-adjacent
        # sensor in the instance.
        "date_shape",
        {"device_class": "date"},
        SensorShape.DATE,
    ),
    (
        # REAL — sensor.washer_detergent_level (device_class "enum")
        "enum_shape",
        {"device_class": "enum"},
        SensorShape.ENUM,
    ),
    (
        # REAL — sensor.sun_next_dawn (device_class "timestamp")
        "timestamp_shape",
        {"device_class": "timestamp"},
        SensorShape.TIMESTAMP,
    ),
    (
        # REAL — sensor.uptime (device_class "uptime")
        "uptime_shape_maps_to_timestamp",
        {"device_class": "uptime"},
        SensorShape.TIMESTAMP,
    ),
]


class TestNumericSensorState:
    def test_is_subclass_of_sensor_state(self) -> None:
        assert issubclass(NumericSensorState, SensorState)

    def test_value_converts_to_float_from_state_dict(self) -> None:
        state_dict = make_sensor_state_dict(
            entity_id="sensor.zone_a_temperature",
            state="21.5",
            device_class="temperature",
            unit_of_measurement="°C",
        )
        state = convert_state_dict_to_model(state_dict, NumericSensorState)

        assert isinstance(state, NumericSensorState)
        assert isinstance(state.value, float)
        assert state.value == pytest.approx(21.5)

    def test_none_value_stays_none(self) -> None:
        state_dict = make_sensor_state_dict(entity_id="sensor.zone_a_temperature", state="unavailable")
        state = convert_state_dict_to_model(state_dict, NumericSensorState)

        assert isinstance(state, NumericSensorState)
        assert state.value is None
        assert state.is_unavailable is True


class TestEnumSensorState:
    def test_is_subclass_of_sensor_state(self) -> None:
        assert issubclass(EnumSensorState, SensorState)

    def test_value_stays_str_from_state_dict(self) -> None:
        state_dict = make_sensor_state_dict(
            entity_id="sensor.zone_a_operating_mode",
            state="eco",
            device_class="enum",
            options=["eco", "boost", "idle"],
        )
        state = convert_state_dict_to_model(state_dict, EnumSensorState)

        assert isinstance(state, EnumSensorState)
        assert isinstance(state.value, str)
        assert state.value == "eco"


class TestTimestampSensorState:
    def test_is_subclass_of_sensor_state(self) -> None:
        assert issubclass(TimestampSensorState, SensorState)

    def test_value_converts_to_zoned_date_time_from_state_dict(self) -> None:
        state_dict = make_sensor_state_dict(
            entity_id="sensor.zone_a_last_backup",
            state="2026-08-01T12:00:00+00:00",
            device_class="timestamp",
        )
        state = convert_state_dict_to_model(state_dict, TimestampSensorState)

        assert isinstance(state, TimestampSensorState)
        assert isinstance(state.value, ZonedDateTime)


class TestDateSensorState:
    def test_is_subclass_of_sensor_state(self) -> None:
        assert issubclass(DateSensorState, SensorState)

    def test_value_converts_to_date_from_state_dict(self) -> None:
        state_dict = make_sensor_state_dict(
            entity_id="sensor.zone_a_filter_expiry",
            state="2026-12-25",
            device_class="date",
        )
        state = convert_state_dict_to_model(state_dict, DateSensorState)

        assert isinstance(state, DateSensorState)
        assert isinstance(state.value, Date)


class TestClassifySensorShape:
    @pytest.mark.parametrize(
        ("attributes", "expected"),
        [(attrs, expected) for _, attrs, expected in CLASSIFIER_FIXTURE],
        ids=[label for label, _, _ in CLASSIFIER_FIXTURE],
    )
    def test_classify(self, attributes: dict[str, Any], expected: SensorShape) -> None:
        assert classify_sensor_shape(attributes) is expected

    def test_unknown_is_distinct_from_every_shape(self) -> None:
        """UNKNOWN must be its own checkable result, not any of the four named shapes."""
        assert classify_sensor_shape({}) is SensorShape.UNKNOWN
        assert SensorShape.UNKNOWN not in (
            SensorShape.NUMERIC,
            SensorShape.ENUM,
            SensorShape.TIMESTAMP,
            SensorShape.DATE,
        )


def test_uptime_device_class_classifies_as_timestamp_shape() -> None:
    """Device class `uptime` maps to the timestamp shape; no separate uptime class exists."""
    assert classify_sensor_shape({"device_class": "uptime"}) is SensorShape.TIMESTAMP


def _run_pyright_narrowing_probe() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "pyright", "--project", str(PYRIGHT_PROBE_DIR), str(PYRIGHT_PROBE_FILE)],
        capture_output=True,
        text=True,
        cwd=str(WORKTREE_ROOT),
        timeout=PYRIGHT_PROBE_TIMEOUT_SECONDS,
    )
    return result.stdout + result.stderr


def test_pyright_narrows_numeric_sensor_state_value_but_not_sensor_state() -> None:
    """Arithmetic on `NumericSensorState.value` type-checks after a `None` guard; the
    identical arithmetic on `SensorState.value` does not.

    Runs pyright against tests/pyright_probes/sensor_shape_probe/narrowing_probe.py, which
    contains one line of each case marked `# PROBE-OK:` / `# PROBE-ERROR:`, and asserts
    reportOperatorIssue fires only on the marked error line.
    """
    try:
        output = _run_pyright_narrowing_probe()
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"pyright timed out after {PYRIGHT_PROBE_TIMEOUT_SECONDS}s — check for a hung pyright process or slow CI"
        )

    if "No module named" in output:
        pytest.fail(
            "pyright is not installed or not runnable as a Python module. "
            "Install it: uv add --dev pyright\n\nOutput:\n" + output
        )

    probe_lines = PYRIGHT_PROBE_FILE.read_text().splitlines()
    error_lineno = next(i for i, line in enumerate(probe_lines, start=1) if "PROBE-ERROR" in line)
    ok_lineno = next(i for i, line in enumerate(probe_lines, start=1) if "PROBE-OK" in line)

    probe_filename = PYRIGHT_PROBE_FILE.name
    error_pattern = rf"{re.escape(probe_filename)}:{error_lineno}:\d+ - error:.*reportOperatorIssue"
    ok_pattern = rf"{re.escape(probe_filename)}:{ok_lineno}:\d+ - error:.*reportOperatorIssue"

    assert re.search(error_pattern, output), (
        f"Expected reportOperatorIssue at line {error_lineno} (SensorState.value arithmetic), "
        f"but no matching diagnostic was found.\n\nPyright output:\n{output}"
    )
    assert not re.search(ok_pattern, output), (
        f"Unexpected reportOperatorIssue at line {ok_lineno} (NumericSensorState.value arithmetic) "
        f"— narrowing may be broken.\n\nPyright output:\n{output}"
    )
