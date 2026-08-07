"""Device-class-specific sensor state subtypes and the shape classifier.

Home Assistant sensors carry four genuinely different value shapes depending on their
device class: numeric, enum, timestamp, and date. `SensorState.value` stays `str | None`
because that class corresponds 1:1 with the `sensor` domain and must accept every sensor.
The four classes below are narrowed *views* of that same domain — each re-declares `value`
with the shape's real Python type, so an app author who names the class up front (via
`D.StateNew[NumericSensorState]`, a `self.states[...]` construction, etc.) gets a typed
value with no cast.

This module is hand-written, not codegen output. `sensor.py` is generated and would
overwrite anything placed there; `templates/state_model.py.j2` renders exactly one
`{{ domain_title }}State` per domain, so teaching it to emit a subclass loop would be
machinery built for four classes that never vary. `codegen/src/hassette_codegen/generators/
exports.py` scans this directory regardless of generated-vs-hand-written status, so the
names here flow into `models/states/__init__.py` and `__all__` automatically.

None of the four classes re-declares `domain`. `BaseState.__init_subclass__` registers a
subclass into the state catalog by reading its *own* `domain` annotation
(`base.py:197-218`, `get_domain()` uses `inspect.get_annotations`, which does not walk the
MRO); re-declaring `domain` here would register a class under `StateKey("sensor")` and
silently replace `SensorState` process-wide. Leaving it undeclared means `get_domain()`
raises `NoDomainAnnotationError`, `__init_subclass__` suppresses it, and the class never
registers — `resolve(domain="sensor")` returns `SensorState` before and after import.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, ClassVar, get_args

from pydantic import AliasChoices, Field
from whenever import Date, ZonedDateTime

from hassette.const.sensor import DEVICE_CLASS, NON_NUMERIC_DEVICE_CLASSES
from hassette.models.states.sensor import SensorState

_KNOWN_DEVICE_CLASSES: frozenset[str] = frozenset(get_args(DEVICE_CLASS))
"""Every `SensorDeviceClass` member, generated from HA core. Used to normalize an unknown
or custom `device_class` string to `None` before classification, mirroring HA's own
`try_parse_enum(SensorDeviceClass, ...)` (`sensor/__init__.py:609`).
"""


class SensorShape(StrEnum):
    """The value shape of a sensor entity, as decided by :func:`classify_sensor_shape`.

    Four shapes correspond to the four narrowed state classes in this module; `UNKNOWN` is
    a fifth, distinct result meaning the entity's metadata gave no basis for a shape claim
    at all (no device class, and no `state_class` or `unit_of_measurement` to infer numeric
    from). `UNKNOWN` is not an error — it means different things to different consumers:
    accessor membership excludes the entity from every narrowed view, while shape
    validation on dependency injection treats it as "no claim to contradict" and does not
    raise.
    """

    NUMERIC = "numeric"
    ENUM = "enum"
    TIMESTAMP = "timestamp"
    DATE = "date"
    UNKNOWN = "unknown"


class NumericSensorState(SensorState):
    """A sensor whose value is a number.

    Applies to sensors that HA's own numeric-value rule expects to hold a number: any
    sensor carrying a `state_class` or `unit_of_measurement`, or a `device_class` outside
    :data:`hassette.const.sensor.NON_NUMERIC_DEVICE_CLASSES`. See
    :func:`classify_sensor_shape` for the exact rule.

    `self.states[NumericSensorState]` is unsupported — this class deliberately does not
    re-declare `domain` (see module docstring), so generic indexing raises
    `NoDomainAnnotationError`. Use `self.states.numeric_sensor` instead.
    """

    accessor_hint: ClassVar[str | None] = "numeric_sensor"

    value_type: ClassVar[type[Any] | tuple[type[Any], ...]] = (float, type(None))

    value: float | None = Field(..., validation_alias=AliasChoices("state", "value"))
    """The sensor's numeric value, or `None` if unknown/unavailable."""


class EnumSensorState(SensorState):
    """A sensor whose value is one of a fixed set of string options.

    Applies to sensors with `device_class: enum`. The valid options, when the integration
    reports them, are on `attributes.options` (`SensorAttributes.options`).

    `self.states[EnumSensorState]` is unsupported — this class deliberately does not
    re-declare `domain` (see module docstring), so generic indexing raises
    `NoDomainAnnotationError`. Use `self.states.enum_sensor` instead.
    """

    accessor_hint: ClassVar[str | None] = "enum_sensor"

    value_type: ClassVar[type[Any] | tuple[type[Any], ...]] = (str, type(None))

    value: str | None = Field(..., validation_alias=AliasChoices("state", "value"))
    """The sensor's current option value, or `None` if unknown/unavailable."""


class TimestampSensorState(SensorState):
    """A sensor whose value is a timezone-aware point in time.

    Applies to sensors with `device_class: timestamp` **or** `device_class: uptime`. HA
    renders both through the identical branch of its own `state` property
    (`sensor/__init__.py:657-674`) — `uptime` differs only by a drift-normalization step
    that does not change the value's type, so there is no separate uptime class.

    `self.states[TimestampSensorState]` is unsupported — this class deliberately does not
    re-declare `domain` (see module docstring), so generic indexing raises
    `NoDomainAnnotationError`. Use `self.states.timestamp_sensor` instead.
    """

    accessor_hint: ClassVar[str | None] = "timestamp_sensor"

    value_type: ClassVar[type[Any] | tuple[type[Any], ...]] = (ZonedDateTime, type(None))

    value: ZonedDateTime | None = Field(..., validation_alias=AliasChoices("state", "value"))
    """The sensor's timezone-aware timestamp, or `None` if unknown/unavailable."""


class DateSensorState(SensorState):
    """A sensor whose value is a calendar date with no time component.

    Applies to sensors with `device_class: date`.

    `self.states[DateSensorState]` is unsupported — this class deliberately does not
    re-declare `domain` (see module docstring), so generic indexing raises
    `NoDomainAnnotationError`. Use `self.states.date_sensor` instead.
    """

    accessor_hint: ClassVar[str | None] = "date_sensor"

    value_type: ClassVar[type[Any] | tuple[type[Any], ...]] = (Date, type(None))

    value: Date | None = Field(..., validation_alias=AliasChoices("state", "value"))
    """The sensor's calendar date, or `None` if unknown/unavailable."""


def classify_sensor_shape(attributes: Mapping[str, Any]) -> SensorShape:
    """Classify a sensor entity's value shape from its raw state attributes.

    Takes the raw `attributes` mapping from a Home Assistant state dict
    (`state["attributes"]`), not a parsed `SensorAttributes` model — `DomainStates`
    receives `HassStateDict` from `state_proxy.yield_domain_states()`, so taking a parsed
    model would force a Pydantic construction on every membership check across all four
    `Mapping` methods a narrowed accessor implements. Reads three keys as plain strings:
    `device_class`, `state_class`, `unit_of_measurement`.

    Before branching, an unrecognized `device_class` string is normalized to `None` — see
    `_KNOWN_DEVICE_CLASSES`. Without this step a custom device class would satisfy the
    numeric branch's `device_class is not None` fallback and misclassify as numeric, which
    is the exact false positive this classifier exists to prevent. A non-string `device_class`
    (e.g. malformed upstream data reporting a list) is normalized the same way, before the
    `_KNOWN_DEVICE_CLASSES` membership check ever runs — membership testing an unhashable
    value would raise `TypeError` instead of just failing to match.

    Args:
        attributes: The raw `attributes` mapping from a Home Assistant state dict.

    Returns:
        The classified `SensorShape`. `SensorShape.UNKNOWN` is a distinct, checkable
        result, not a fallback error value — see `SensorShape` for what it means to each
        consumer.
    """
    device_class = attributes.get("device_class")
    if not isinstance(device_class, str) or device_class not in _KNOWN_DEVICE_CLASSES:
        device_class = None

    if device_class == "date":
        return SensorShape.DATE
    if device_class == "enum":
        return SensorShape.ENUM
    if device_class in ("timestamp", "uptime"):
        return SensorShape.TIMESTAMP

    state_class = attributes.get("state_class")
    unit_of_measurement = attributes.get("unit_of_measurement")
    if _numeric_state_expected(device_class, state_class, unit_of_measurement):
        return SensorShape.NUMERIC

    return SensorShape.UNKNOWN


def _numeric_state_expected(
    device_class: str | None,
    state_class: str | None,
    unit_of_measurement: str | None,
) -> bool:
    """Port of Home Assistant's `_numeric_state_expected`.

    Source: `~/source/core/homeassistant/components/sensor/__init__.py:126-145`. The
    upstream source is pinned at `codegen/snapshots/numeric_state_expected.py.txt`; codegen's
    freshness check fails when upstream no longer matches that snapshot, forcing a human to
    re-verify this port at version-bump time.

    Two documented divergences from upstream:

    1. Reads `unit_of_measurement` where HA reads `native_unit_of_measurement` — a sensor
       with a native unit always has a display unit in state attributes, so the two are
       equivalent here.
    2. Drops the `suggested_display_precision` term — that attribute never reaches real
       state attributes (0 of 270 sensors on a live instance carried it), so it can never
       change the result in practice.

    Both divergences, and the numeric branch's overall behavior, are pinned by the
    fixture test in `tests/unit/models/test_sensor_shapes.py`.

    Args:
        device_class: The entity's `device_class`, already normalized to `None` for any
            unrecognized/custom string by the caller (`classify_sensor_shape`).
        state_class: The entity's `state_class`, or `None`.
        unit_of_measurement: The entity's `unit_of_measurement`, or `None`.

    Returns:
        Whether the sensor's value is expected to be numeric.
    """
    # Note: the order of the checks is kept aligned with HA's `_numeric_state_expected`,
    # even though `classify_sensor_shape` already special-cases `date`, `enum`, `timestamp`,
    # and `uptime` before ever calling this function — which makes this
    # NON_NUMERIC_DEVICE_CLASSES check technically unreachable from that caller. It stays
    # anyway so this function remains a line-for-line diffable port of upstream: a
    # restructured port would make the diff against
    # `codegen/snapshots/numeric_state_expected.py.txt` useless when upstream changes.
    if device_class in NON_NUMERIC_DEVICE_CLASSES:
        return False
    if state_class is not None or unit_of_measurement is not None:
        return True
    # Sensors with custom device classes were already normalized to None by
    # classify_sensor_shape's caller; a real device class outside NON_NUMERIC_DEVICE_CLASSES
    # still counts as numeric.
    return device_class is not None
