"""RecordingApi.get_state_value / get_attribute match production Api semantics on seeded states."""

import pytest

from hassette.const.misc import MISSING_VALUE
from hassette.exceptions import EntityNotFoundError
from hassette.testing import RecordingApi, make_state_dict
from tests.support.factories import make_recording_api


def make_value_read_api() -> RecordingApi:
    """RecordingApi seeded with a sensor carrying nested attributes and an unavailable light."""
    sensor = make_state_dict(
        entity_id="sensor.temp",
        state="21.5",
        attributes={"unit_of_measurement": "°C", "forecast": {"high": {"value": 30}}},
    )
    unavailable = make_state_dict(entity_id="light.porch", state="unavailable", attributes={})
    return make_recording_api(states={"sensor.temp": sensor, "light.porch": unavailable})


async def test_get_state_value_returns_raw_state_string():
    """get_state_value returns the raw HA state string, like Api.get_state_value."""
    api = make_value_read_api()
    assert await api.get_state_value("sensor.temp") == "21.5"
    assert api.sync.get_state_value("sensor.temp") == "21.5"


async def test_get_state_value_returns_unavailable_verbatim():
    """get_state_value returns "unavailable" as-is rather than converting it."""
    api = make_value_read_api()
    assert await api.get_state_value("light.porch") == "unavailable"
    assert api.sync.get_state_value("light.porch") == "unavailable"


async def test_get_state_value_missing_entity_raises():
    """get_state_value raises EntityNotFoundError for an unseeded entity, async and sync."""
    api = make_value_read_api()
    with pytest.raises(EntityNotFoundError):
        await api.get_state_value("sensor.missing")
    with pytest.raises(EntityNotFoundError):
        api.sync.get_state_value("sensor.missing")


async def test_get_attribute_returns_top_level_and_nested_values():
    """get_attribute resolves plain names and dot-separated paths, async and sync."""
    api = make_value_read_api()
    assert await api.get_attribute("sensor.temp", "unit_of_measurement") == "°C"
    assert await api.get_attribute("sensor.temp", "forecast.high.value") == 30
    assert api.sync.get_attribute("sensor.temp", "forecast.high.value") == 30


async def test_get_attribute_missing_attribute_returns_sentinel():
    """get_attribute returns MISSING_VALUE for an absent attribute, async and sync."""
    api = make_value_read_api()
    assert await api.get_attribute("sensor.temp", "nope") is MISSING_VALUE
    assert api.sync.get_attribute("sensor.temp", "forecast.low") is MISSING_VALUE


async def test_get_attribute_missing_entity_raises():
    """get_attribute raises EntityNotFoundError for an unseeded entity, async and sync."""
    api = make_value_read_api()
    with pytest.raises(EntityNotFoundError):
        await api.get_attribute("sensor.missing", "unit_of_measurement")
    with pytest.raises(EntityNotFoundError):
        api.sync.get_attribute("sensor.missing", "unit_of_measurement")
