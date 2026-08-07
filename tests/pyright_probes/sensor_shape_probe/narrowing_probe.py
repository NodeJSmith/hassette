"""Pyright probe proving `NumericSensorState.value` narrows to `float | None`.

`SensorState.value` is `str | None`, so arithmetic on it (even after a `None` guard) is a
type error — that's the exact friction this feature exists to remove. `NumericSensorState`
re-declares `value` as `float | None`, so the same arithmetic, after the same guard, must
type-check cleanly.

This file is INTENTIONALLY split into a passing case and a failing case in the same probe,
proving both halves in one run: the narrowed subclass allows the arithmetic, the base class
still does not.

Checked by a dedicated pyrightconfig at tests/pyright_probes/sensor_shape_probe/pyrightconfig.json
that keeps reportOperatorIssue at its basic-mode default of "error" — the shared
tests/pyright_probes/pyrightconfig.json mutes reportOperatorIssue entirely (needed for the
MagicMock-heavy forgotten-await probe), so this probe cannot reuse it.

The unit test at tests/unit/models/test_sensor_shapes.py runs pyright on this file and
asserts reportOperatorIssue fires on the SensorState line but not on the NumericSensorState
line.
"""

# ruff: noqa
# pyright: basic

from hassette.models.states.sensor import SensorState
from hassette.models.states.sensor_shapes import NumericSensorState


def probe_numeric_sensor_arithmetic_ok(state: NumericSensorState) -> float:
    if state.value is None:
        return 0.0
    return state.value + 1  # PROBE-OK: numeric_sensor_value_arithmetic


def probe_sensor_state_arithmetic_errors(state: SensorState) -> object:
    if state.value is None:
        return None
    return state.value + 1  # PROBE-ERROR: sensor_state_value_arithmetic
