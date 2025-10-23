from types import SimpleNamespace

import pytest

from hassette.config.core_config import HassetteConfig
from hassette.utils.url_utils import build_rest_url, build_ws_url


@pytest.mark.parametrize(
    ("provided_address", "expected_rest_url", "expected_ws_url"),
    [
        ("localhost", "http://localhost:8123/api/", "ws://localhost:8123/api/websocket"),
        ("http://example.com", "http://example.com:8123/api/", "ws://example.com:8123/api/websocket"),
        ("https://example.com", "https://example.com:8123/api/", "wss://example.com:8123/api/websocket"),
    ],
)
def test_base_url_without_scheme_uses_http_and_ws(provided_address, expected_rest_url, expected_ws_url):
    c = HassetteConfig.model_construct(_fields_set=set())
    hassette = SimpleNamespace()

    c.base_url = provided_address

    hassette.rest_url = build_rest_url(c)
    hassette.ws_url = build_ws_url(c)

    assert hassette.rest_url == expected_rest_url, f"rest_url was {hassette.rest_url}, expected {expected_rest_url}"
    assert hassette.ws_url == expected_ws_url, f"ws_url was {hassette.ws_url}, expected {expected_ws_url}"
