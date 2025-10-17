import inspect

from hassette.core.resources.api.api import Api
from hassette.core.resources.api.sync import ApiSyncFacade
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


def test_sync_parity():
    """Sync facade exposes the same public methods as the async API."""
    api_methods = inspect.getmembers(Api, predicate=inspect.isfunction)
    api_sync_methods = inspect.getmembers(ApiSyncFacade, predicate=inspect.isfunction)

    api_method_names = {name for name, _ in api_methods if not name.startswith("_")}
    api_sync_method_names = {name for name, _ in api_sync_methods if not name.startswith("_")}

    assert api_method_names == api_sync_method_names, f"Mismatch: {api_method_names ^ api_sync_method_names}"
