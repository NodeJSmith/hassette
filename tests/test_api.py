import inspect
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import orjson
import pytest

from hassette.core.api import Api, ApiSyncFacade, _Api, clean_kwargs


@pytest.fixture
def mock_api():
    mock = _Api(Mock())
    mock._session = AsyncMock()
    mock._session.request.return_value = Mock()
    return mock


async def test_api_rest_request_sets_body_and_headers(mock_api: _Api):
    await mock_api._rest_request("POST", "/api/thing", data={"a": 1})

    # casting to keep types linked properly, so refactoring tools work
    req = cast("Mock", mock_api._session.request)

    req.assert_called_once_with(
        "POST",
        "/api/thing",
        data=orjson.dumps({"a": 1}).decode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


@patch("hassette.core.api.clean_kwargs")
async def test_api_rest_request_cleans_params(mock_clean: Mock, mock_api: _Api):
    params = {"keep": "x", "none": None, "empty": "  ", "flag": False}

    await mock_api._rest_request("GET", "/api/thing", params=params)

    mock_clean.assert_called_once_with(**params)


def test_clean_kwargs_basic():
    out = clean_kwargs(a=None, b=False, c="  ", d="x", e=5)
    assert out == {"b": "false", "d": "x", "e": 5}


def test_sync_parity():
    api_methods = inspect.getmembers(Api, predicate=inspect.isfunction)
    api_sync_methods = inspect.getmembers(ApiSyncFacade, predicate=inspect.isfunction)

    api_method_names = {name for name, _ in api_methods if not name.startswith("_")}
    api_sync_method_names = {name for name, _ in api_sync_methods if not name.startswith("_")}

    assert api_method_names == api_sync_method_names, f"Mismatch: {api_method_names ^ api_sync_method_names}"
