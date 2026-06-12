from typing import Any

from hassette import STATE_REGISTRY
from hassette.api import Api
from hassette.models.entities.light import LightEntity
from hassette.test_utils import SimpleTestServer
from hassette.utils.request_utils import clean_kwargs


async def test_api_rest_request_sets_body_and_headers(hassette_with_mock_api: tuple[Api, SimpleTestServer]):
    """POST requests include JSON body and expected headers."""
    api_client, mock_server = hassette_with_mock_api

    mock_server.expect("POST", "/api/thing", "", json={"a": 1}, status=200)

    response = await api_client.rest_request("POST", "/api/thing", data={"a": 1})
    payload = await response.json()

    assert "application/json" in response.headers.get("Content-Type", ""), "Expected JSON response"
    assert payload == {"a": 1}, f"Expected echoed JSON, got {payload}"


async def test_api_rest_request_cleans_params(hassette_with_mock_api: tuple[Api, SimpleTestServer]):
    """Query parameters are cleaned before sending a GET request."""
    api_client, mock_server = hassette_with_mock_api

    request_params = {"keep": "x", "none": None, "empty": "  ", "flag": False}

    mock_server.expect("GET", "/api/thing", "keep=x&flag=false", status=200)

    response = await api_client.rest_request("GET", "/api/thing", params=request_params)

    assert response.status == 200, f"Expected 200 OK, got {response.status}"

    assert dict(response.request_info.url.query) == {"keep": "x", "flag": "false"}, (
        f"Unexpected query params: {response.request_info.url.query}"
    )


def test_clean_kwargs_basic():
    """clean_kwargs drops empty values and normalises booleans."""
    cleaned_kwargs = clean_kwargs(a=None, b=False, c="  ", d="x", e=5)
    assert cleaned_kwargs == {"b": "false", "d": "x", "e": 5}, f"Unexpected cleaned kwargs: {cleaned_kwargs}"


async def test_get_state_return_type(
    hassette_with_mock_api: tuple[Api, SimpleTestServer], hass_state_dicts: list[dict[str, Any]]
):
    """get_state returns the correct type."""
    api_client, mock_server = hassette_with_mock_api

    for state_dict in hass_state_dicts:
        entity_id = state_dict["entity_id"]
        mock_server.expect("GET", f"/api/states/{entity_id}", "", json=state_dict, status=200)

        state = await api_client.get_state(entity_id)

        assert state is not None, f"Expected state for {entity_id}, got None"
        assert state.entity_id == entity_id, f"Expected entity_id {entity_id}, got {state.entity_id}"

        # Check specific types
        domain = entity_id.split(".")[0]
        expected_class = STATE_REGISTRY.resolve(domain=domain)
        assert isinstance(state, expected_class), f"Expected {expected_class}, got {type(state)}"


async def test_get_state_or_none_returns_none_for_missing_entity(
    hassette_with_mock_api: tuple[Api, SimpleTestServer],
):
    """get_state_or_none returns None when the entity does not exist.

    Regression test: the REST layer converts 404 responses to EntityNotFoundError,
    but get_state_or_none caught aiohttp.ClientResponseError, so the error escaped
    instead of returning None as documented.
    """
    api_client, mock_server = hassette_with_mock_api

    mock_server.expect("GET", "/api/states/light.nonexistent", "", json={"message": "not found"}, status=404)

    result = await api_client.get_state_or_none("light.nonexistent")

    assert result is None, f"Expected None for missing entity, got {result!r}"


async def test_get_entity_or_none_returns_none_for_missing_entity(
    hassette_with_mock_api: tuple[Api, SimpleTestServer],
):
    """get_entity_or_none returns None when the entity does not exist (same root cause as above)."""
    api_client, mock_server = hassette_with_mock_api

    mock_server.expect("GET", "/api/states/light.nonexistent", "", json={"message": "not found"}, status=404)

    result = await api_client.get_entity_or_none("light.nonexistent", LightEntity)

    assert result is None, f"Expected None for missing entity, got {result!r}"
