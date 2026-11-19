"""What an app instance declares through ``self.integration``, and the rules its values follow.

A declaration describes one entity: its key, platform and display fields. Its state is a value plus attributes.
Values follow Home Assistant's sensor rules (spec 157 D5): the sensor's shape, from ``classify_sensor_shape``,
decides which Python types ``set()`` accepts.
"""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeAlias, get_args

from whenever import Date, Instant, OffsetDateTime, ZonedDateTime

from hassette.config.classes import instance_name_reason
from hassette.const.sensor import DEVICE_CLASS, STATE_CLASS
from hassette.models.states.sensor_shapes import SensorShape, classify_sensor_shape
from hassette.utils.hass_utils import VALID_ENTITY_ID

KNOWN_DEVICE_CLASSES: frozenset[str] = frozenset(get_args(DEVICE_CLASS))
KNOWN_STATE_CLASSES: frozenset[str] = frozenset(get_args(STATE_CLASS))

AWARE_TYPES = (Instant, ZonedDateTime, OffsetDateTime)
"""The ``whenever`` types a timestamp sensor accepts; each is normalized to an ``Instant``."""

EntityValue: TypeAlias = bool | int | float | str | Instant | Date | None
"""A switch's or sensor's value as a handle exposes it. ``None`` is a sensor's ``unknown``."""


class IntegrationPlatform(StrEnum):
    """The Home Assistant platform a declaration creates an entity on."""

    BUTTON = "button"
    SWITCH = "switch"
    SENSOR = "sensor"


@dataclass(frozen=True, slots=True)
class Declaration:
    """One declared entity: everything that describes it, without its state.

    ``initial`` is set for a switch only; ``unit``, ``device_class``, ``state_class`` and ``options`` for a
    sensor only.
    """

    key: str
    platform: IntegrationPlatform
    name: str
    default_entity_id: str | None = None
    initial: bool | None = None
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    options: tuple[str, ...] | None = None

    @property
    def shape(self) -> SensorShape:
        """The sensor's value shape; ``UNKNOWN`` (a string sensor) for one with no basis for another."""
        return classify_sensor_shape(
            {"device_class": self.device_class, "state_class": self.state_class, "unit_of_measurement": self.unit}
        )


@dataclass(frozen=True, slots=True)
class EntityState:
    """A switch's or sensor's state: its value and attributes, replaced together by ``set()`` (spec 157 D13)."""

    value: EntityValue = None
    attributes: Mapping[str, Any] = field(default_factory=dict)


def default_state(declaration: Declaration) -> EntityState:
    """The state of an entity with nothing stored: a switch's ``initial`` (off by default), a sensor's unknown."""
    if declaration.platform is IntegrationPlatform.SWITCH:
        return EntityState(value=bool(declaration.initial))
    return EntityState()


def resolve_state(
    declaration: Declaration, pending: EntityState | None, restored: EntityState | None
) -> tuple[EntityState, bool]:
    """The state an entity starts its run with, and whether a restored value was reset (spec 157 D12).

    Its pending ``set()`` value, else its restored state if the declaration accepts it, else its default. The
    one home of that precedence: the handle reads it during initialization, and the commit applies it.
    """
    if declaration.platform is IntegrationPlatform.BUTTON:
        return EntityState(), False
    if pending is not None:
        return pending, False
    if restored is None:
        return default_state(declaration), False
    if fits(declaration, restored.value):
        return restored, False
    return default_state(declaration), True


def validate_key(key: object, platform: IntegrationPlatform) -> str:
    """Return ``key`` if it follows the ``instance_name`` rule, else raise ``ValueError``."""
    if not isinstance(key, str):
        raise ValueError(f"{platform} key must be a string, got {key!r}")
    if reason := instance_name_reason(key):
        raise ValueError(f"{platform} key {key!r} {reason}")
    return key


def validate_default_entity_id(default_entity_id: str | None, platform: IntegrationPlatform) -> str | None:
    """Return ``default_entity_id`` if it is ``None`` or a valid entity id on ``platform``; else raise ``ValueError``.

    A valid one is ``<platform>.<object_id>``, with an object id of lowercase letters, digits and ``_``.
    """
    if default_entity_id is None:
        return None
    domain, _, _ = default_entity_id.partition(".")
    if domain != platform or not VALID_ENTITY_ID.fullmatch(default_entity_id):
        raise ValueError(
            f"default_entity_id {default_entity_id!r} must be '{platform}.<object_id>', where the object id uses "
            "only lowercase letters, digits and '_', and doesn't start or end with '_'"
        )
    return default_entity_id


def validate_sensor_fields(
    key: str,
    *,
    device_class: str | None,
    state_class: str | None,
    options: list[str] | tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    """Check a sensor declaration's fields the way Home Assistant does; return ``options`` as a tuple.

    Raises:
        ValueError: An unknown device or state class, an enum sensor without options, or options on a sensor
            that isn't an enum sensor.
    """
    if device_class is not None and device_class not in KNOWN_DEVICE_CLASSES:
        raise ValueError(f"sensor {key!r} has unknown device_class {device_class!r}")
    if state_class is not None and state_class not in KNOWN_STATE_CLASSES:
        valid = ", ".join(sorted(KNOWN_STATE_CLASSES))
        raise ValueError(f"sensor {key!r} has unknown state_class {state_class!r}; use one of {valid}")
    if device_class == "enum":
        if not options or not all(isinstance(option, str) for option in options):
            raise ValueError(f"enum sensor {key!r} needs options, a non-empty list of strings")
        if len(set(options)) != len(options):
            raise ValueError(f"enum sensor {key!r} has duplicate options")
        return tuple(options)
    if options is not None:
        raise ValueError(f"sensor {key!r} has options, which only an enum sensor (device_class='enum') takes")
    return None


def check_value(declaration: Declaration, value: object) -> EntityValue:
    """Return ``value`` as the declaration stores it, or raise ``ValueError`` if the declaration rejects it.

    A switch takes a ``bool``. A sensor takes ``None`` (unknown) or a value of its shape: a number (never a
    ``bool``) for a numeric sensor, one of its options for an enum sensor, an aware ``whenever`` type for a
    timestamp sensor (normalized to ``Instant``), a ``whenever.Date`` for a date sensor, and a string otherwise.
    """
    key = declaration.key
    if declaration.platform is IntegrationPlatform.BUTTON:
        raise ValueError(f"button {key!r} has no state")
    if declaration.platform is IntegrationPlatform.SWITCH:
        if not isinstance(value, bool):
            raise ValueError(f"switch {key!r} takes a bool, got {value!r}")
        return value
    if value is None:
        return None
    shape = declaration.shape
    if shape is SensorShape.NUMERIC:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"numeric sensor {key!r} takes an int or float, got {value!r}")
        if not math.isfinite(value):
            raise ValueError(f"numeric sensor {key!r} takes a finite number, got {value!r}")
        return value
    if shape is SensorShape.ENUM:
        if value not in (declaration.options or ()):
            raise ValueError(f"enum sensor {key!r} takes one of {list(declaration.options or ())}, got {value!r}")
        return value  # pyright: ignore[reportReturnType]  # membership in the str options proves it's a str
    if shape is SensorShape.TIMESTAMP:
        if not isinstance(value, AWARE_TYPES):
            raise ValueError(
                f"timestamp sensor {key!r} takes a whenever Instant, ZonedDateTime or OffsetDateTime, got {value!r}"
            )
        return value if isinstance(value, Instant) else value.to_instant()
    if shape is SensorShape.DATE:
        if not isinstance(value, Date):
            raise ValueError(f"date sensor {key!r} takes a whenever Date, got {value!r}")
        return value
    if not isinstance(value, str):
        raise ValueError(
            f"sensor {key!r} takes a string (it has no numeric, enum, timestamp or date shape), got {value!r}"
        )
    return value


def fits(declaration: Declaration, value: EntityValue) -> bool:
    """Whether ``declaration`` accepts ``value`` unchanged, as a restored value must (spec 157 D12)."""
    try:
        return check_value(declaration, value) == value
    except ValueError:
        return False


def check_attributes(key: str, attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return ``attributes`` as a deep copy in stored (JSON) form, or raise ``ValueError`` if it isn't a JSON object.

    The copy shares nothing with the caller, so mutating the caller's dict later can't change committed state.
    """
    if attributes is None:
        return {}
    if not isinstance(attributes, Mapping) or not all(isinstance(name, str) for name in attributes):
        raise ValueError(f"{key!r} attributes must be a mapping with string keys")
    try:
        encoded = json.dumps(attributes, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key!r} attributes must be JSON-serializable: {exc}") from exc
    return json.loads(encoded)


def encode_value(value: EntityValue) -> str | None:
    """Encode a value for the value column: JSON, with a timestamp or date as its ISO 8601 string."""
    if value is None:
        return None
    if isinstance(value, Instant | Date):
        return json.dumps(value.format_iso())
    return json.dumps(value, allow_nan=False)


def decode_value(declaration: Declaration, text: str | None) -> EntityValue:
    """Decode a value column back to the type ``declaration`` gives its handle.

    Raises:
        ValueError: The stored text doesn't parse as the declaration's type.
    """
    if text is None:
        return None
    raw = json.loads(text)
    if declaration.platform is IntegrationPlatform.SENSOR and isinstance(raw, str):
        shape = declaration.shape
        if shape is SensorShape.TIMESTAMP:
            return Instant.parse_iso(raw)
        if shape is SensorShape.DATE:
            return Date.parse_iso(raw)
    if raw is not None and not isinstance(raw, bool | int | float | str):
        raise ValueError(f"stored value for {declaration.key!r} is not a JSON scalar: {text!r}")
    return raw
