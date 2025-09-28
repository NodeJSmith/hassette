import inspect

from hassette.core.api import Api, ApiSyncFacade, clean_kwargs
from hassette.test_utils import SimpleTestServer


async def test_api_rest_request_sets_body_and_headers(hassette_with_mock_api: tuple[Api, SimpleTestServer]):
    api, mock = hassette_with_mock_api

    mock.expect("POST", "/api/thing", "", json={"a": 1}, status=200)

    resp = await api.rest_request("POST", "/api/thing", data={"a": 1})
    resp_data = await resp.json()

    assert "application/json" in resp.headers.get("Content-Type", "")
    assert resp_data == {"a": 1}


async def test_api_rest_request_cleans_params(hassette_with_mock_api: tuple[Api, SimpleTestServer]):
    api, mock = hassette_with_mock_api

    params = {"keep": "x", "none": None, "empty": "  ", "flag": False}

    mock.expect("GET", "/api/thing", "keep=x&flag=false", status=200)

    resp = await api.rest_request("GET", "/api/thing", params=params)

    assert resp.status == 200

    assert dict(resp.request_info.url.query) == {"keep": "x", "flag": "false"}


def test_clean_kwargs_basic():
    out = clean_kwargs(a=None, b=False, c="  ", d="x", e=5)
    assert out == {"b": "false", "d": "x", "e": 5}


def test_sync_parity():
    api_methods = inspect.getmembers(Api, predicate=inspect.isfunction)
    api_sync_methods = inspect.getmembers(ApiSyncFacade, predicate=inspect.isfunction)

    api_method_names = {name for name, _ in api_methods if not name.startswith("_")}
    api_sync_method_names = {name for name, _ in api_sync_methods if not name.startswith("_")}

    assert api_method_names == api_sync_method_names, f"Mismatch: {api_method_names ^ api_sync_method_names}"
