"""Declaration and value rules for app-declared entities (spec 157 D5, D6, D12)."""

from types import MappingProxyType

import pytest
from whenever import Date, Instant, OffsetDateTime, ZonedDateTime, hours

from hassette.integration.declarations import (
    Declaration,
    IntegrationPlatform,
    check_attributes,
    check_value,
    decode_value,
    default_state,
    encode_value,
    fits,
    validate_default_entity_id,
    validate_entity_category,
    validate_key,
    validate_name,
    validate_sensor_fields,
)

SWITCH = Declaration(key="show", platform=IntegrationPlatform.SWITCH, name="Show", initial=True)
BUTTON = Declaration(key="feed", platform=IntegrationPlatform.BUTTON, name="Feed")
NUMERIC = Declaration(key="temp", platform=IntegrationPlatform.SENSOR, name="T", device_class="temperature", unit="°C")
ENUM = Declaration(key="mode", platform=IntegrationPlatform.SENSOR, name="M", device_class="enum", options=("a", "b"))
TIMESTAMP = Declaration(key="next", platform=IntegrationPlatform.SENSOR, name="N", device_class="timestamp")
DATE = Declaration(key="day", platform=IntegrationPlatform.SENSOR, name="D", device_class="date")
STRING = Declaration(key="note", platform=IntegrationPlatform.SENSOR, name="Note")


@pytest.mark.parametrize("key", ["Feed", "1feed", "feed_", "feed-cat", "", 5])
def test_invalid_key_raises(key: object) -> None:
    with pytest.raises(ValueError, match="key"):
        validate_key(key, IntegrationPlatform.BUTTON)


def test_valid_key_passes() -> None:
    assert validate_key("feed_cat2", IntegrationPlatform.BUTTON) == "feed_cat2"


@pytest.mark.parametrize("name", [None, 5, ""])
def test_invalid_name_raises(name: object) -> None:
    with pytest.raises(ValueError, match="name must be a non-empty string"):
        validate_name(name, IntegrationPlatform.BUTTON)


def test_valid_name_passes() -> None:
    assert validate_name("Feed cat", IntegrationPlatform.BUTTON) == "Feed cat"


@pytest.mark.parametrize(
    "eid",
    [
        "switch.show",
        "button",
        "button.Feed",
        "button.feed-cat",
        "button.",
        "button._feed",
        "button.feed_",
        "button.feed\n",
    ],
)
def test_invalid_default_entity_id_raises(eid: str) -> None:
    with pytest.raises(ValueError, match="default_entity_id"):
        validate_default_entity_id(eid, IntegrationPlatform.BUTTON)


def test_non_string_default_entity_id_raises_value_error() -> None:
    with pytest.raises(ValueError, match="default_entity_id must be a string"):
        validate_default_entity_id(123, IntegrationPlatform.BUTTON)


def test_default_entity_id_on_matching_platform_passes() -> None:
    assert validate_default_entity_id("button.feed_cat", IntegrationPlatform.BUTTON) == "button.feed_cat"
    assert validate_default_entity_id(None, IntegrationPlatform.BUTTON) is None


@pytest.mark.parametrize("category", ["config", "diagnostic", None])
def test_valid_entity_category_passes(category: str | None) -> None:
    assert validate_entity_category(category, IntegrationPlatform.SWITCH) == category


@pytest.mark.parametrize("category", ["system", "Config", "", 1, [], {}])
def test_invalid_entity_category_raises(category: object) -> None:
    with pytest.raises(ValueError, match="entity_category must be one of 'config', 'diagnostic' or None"):
        validate_entity_category(category, IntegrationPlatform.SWITCH)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"device_class": "not_a_class", "state_class": None, "unit": None, "options": None}, "unknown device_class"),
        ({"device_class": None, "state_class": "sometimes", "unit": None, "options": None}, "unknown state_class"),
        ({"device_class": "enum", "state_class": None, "unit": None, "options": None}, "needs options"),
        ({"device_class": "enum", "state_class": None, "unit": None, "options": []}, "needs options"),
        ({"device_class": "enum", "state_class": None, "unit": None, "options": "auto"}, "needs options"),
        ({"device_class": "enum", "state_class": None, "unit": None, "options": ["a", "a"]}, "duplicate"),
        ({"device_class": None, "state_class": None, "unit": None, "options": "auto"}, "must be a list of strings"),
        ({"device_class": "temperature", "state_class": None, "unit": None, "options": ["a"]}, "only an enum sensor"),
        ({"device_class": "enum", "state_class": "measurement", "unit": None, "options": ["a"]}, "state_class or unit"),
        ({"device_class": "enum", "state_class": None, "unit": "g", "options": ["a"]}, "state_class or unit"),
    ],
)
def test_invalid_sensor_fields_raise(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        validate_sensor_fields("s", **kwargs)


def test_enum_options_become_a_tuple() -> None:
    assert validate_sensor_fields("s", device_class="enum", state_class=None, unit=None, options=["a", "b"]) == (
        "a",
        "b",
    )


@pytest.mark.parametrize(
    ("declaration", "value"),
    [
        (SWITCH, 1),
        (SWITCH, None),
        (NUMERIC, True),
        (NUMERIC, "5"),
        (NUMERIC, float("nan")),
        (ENUM, "c"),
        (TIMESTAMP, "2026-01-01T00:00:00Z"),
        (DATE, Instant.now()),
        (STRING, 5),
    ],
)
def test_check_value_rejects_values_the_declaration_rejects(declaration: Declaration, value: object) -> None:
    with pytest.raises(ValueError, match=declaration.key):
        check_value(declaration, value)


def test_button_has_no_state() -> None:
    with pytest.raises(ValueError, match="no state"):
        check_value(BUTTON, None)


def test_check_value_accepts_and_normalizes() -> None:
    now = Instant.now()
    assert check_value(SWITCH, False) is False
    assert check_value(NUMERIC, 5) == 5
    assert check_value(NUMERIC, 2.5) == 2.5
    assert check_value(ENUM, "b") == "b"
    assert check_value(DATE, Date(2026, 1, 2)) == Date(2026, 1, 2)
    assert check_value(STRING, "hello") == "hello"
    assert check_value(NUMERIC, None) is None
    assert check_value(TIMESTAMP, now) == now
    assert check_value(TIMESTAMP, now.to_tz("Europe/Paris")) == now
    assert isinstance(check_value(TIMESTAMP, ZonedDateTime(2026, 1, 1, tz="UTC")), Instant)
    offset = OffsetDateTime(2026, 1, 1, offset=hours(2))
    assert check_value(TIMESTAMP, offset) == offset.to_instant()


def test_fits_reports_whether_a_restored_value_still_fits() -> None:
    assert fits(NUMERIC, 21.5)
    assert not fits(ENUM, 21.5)
    assert fits(ENUM, None)
    assert not fits(SWITCH, None)


@pytest.mark.parametrize(
    ("declaration", "value"),
    [
        (SWITCH, True),
        (NUMERIC, 21.5),
        (NUMERIC, 3),
        (ENUM, "a"),
        (TIMESTAMP, Instant.from_utc(2026, 1, 1, 12)),
        (DATE, Date(2026, 1, 2)),
        (STRING, "x"),
        (STRING, None),
    ],
)
def test_values_round_trip_through_the_value_column(declaration: Declaration, value: object) -> None:
    assert decode_value(declaration, encode_value(value)) == value  # pyright: ignore[reportArgumentType]


def test_timestamp_is_stored_as_iso_8601_with_offset() -> None:
    assert encode_value(Instant.from_utc(2026, 1, 1, 12)) == '"2026-01-01T12:00:00Z"'
    assert encode_value(Date(2026, 1, 2)) == '"2026-01-02"'


def test_decode_value_raises_on_unparseable_text() -> None:
    with pytest.raises(ValueError, match="invalid ISO 8601"):
        decode_value(TIMESTAMP, '"not a time"')


def test_check_attributes() -> None:
    assert check_attributes("k", None) == {}
    assert check_attributes("k", {"x": 1}) == {"x": 1}
    assert check_attributes("k", MappingProxyType({"x": 1})) == {"x": 1}
    with pytest.raises(ValueError, match="JSON"):
        check_attributes("k", {"x": object()})
    with pytest.raises(ValueError, match="string keys"):
        check_attributes("k", {1: "x"})  # pyright: ignore[reportArgumentType]


def test_default_state() -> None:
    assert default_state(SWITCH).value is True
    assert default_state(Declaration(key="s", platform=IntegrationPlatform.SWITCH, name="S")).value is False
    assert default_state(NUMERIC).value is None
