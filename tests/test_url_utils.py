"""Comprehensive tests for URL utility functions."""

import pytest
from pydantic import SecretStr

from hassette.config.core_config import HassetteConfig
from hassette.exceptions import IPV6NotSupportedError, SchemeRequiredInBaseUrlError
from hassette.utils.url_utils import build_rest_url, build_ws_url


def _make_config(base_url: str, api_port: int = 8123) -> HassetteConfig:
    """Create a test configuration with the given base_url and api_port."""
    config = HassetteConfig.model_construct(_fields_set=set())
    config.token = SecretStr("test-token")
    config.base_url = base_url
    config.api_port = api_port
    return config


def test_basic_http_with_explicit_port():
    """Test URL construction with explicit HTTP scheme and port."""
    config = _make_config("http://localhost:8123")

    assert build_ws_url(config) == "ws://localhost:8123/api/websocket"
    assert build_rest_url(config) == "http://localhost:8123/api/"


def test_https_scheme_conversion():
    """Test that HTTPS scheme correctly converts to WSS for WebSocket URLs."""
    config = _make_config("https://example.com")

    assert build_ws_url(config) == "wss://example.com:8123/api/websocket"
    assert build_rest_url(config) == "https://example.com:8123/api/"


def test_custom_port_in_url_overrides_api_port():
    """Test that port specified in URL takes precedence over api_port."""
    config = _make_config("http://example.com:9000", api_port=8123)

    assert build_ws_url(config) == "ws://example.com:9000/api/websocket"
    assert build_rest_url(config) == "http://example.com:9000/api/"


def test_https_with_custom_port():
    """Test HTTPS URL with custom port."""
    config = _make_config("https://hass.example.com:8443")

    assert build_ws_url(config) == "wss://hass.example.com:8443/api/websocket"
    assert build_rest_url(config) == "https://hass.example.com:8443/api/"


@pytest.mark.parametrize(
    ("base_url", "expected_ws_scheme", "expected_rest_scheme"),
    [
        ("http://test.local", "ws", "http"),
        ("https://test.local", "wss", "https"),
        ("ftp://test.local", "ws", "ftp"),  # Non-standard scheme
    ],
)
def test_scheme_conversion_parametrized(base_url: str, expected_ws_scheme: str, expected_rest_scheme: str):
    """Test scheme conversion with various input schemes."""
    config = _make_config(base_url)

    ws_url = build_ws_url(config)
    rest_url = build_rest_url(config)

    assert ws_url.startswith(f"{expected_ws_scheme}://")
    assert rest_url.startswith(f"{expected_rest_scheme}://")


@pytest.mark.parametrize(("func"), [build_ws_url, build_rest_url])
def test_config_with_empty_base_url_raises(func):
    """Test that an exception is raised for URLs without schemes."""
    config = _make_config("")

    with pytest.raises(SchemeRequiredInBaseUrlError):
        func(config)


@pytest.mark.parametrize(("func"), [build_ws_url, build_rest_url])
def test_ipv6_address(func):
    """Test IPv6 address handling."""
    config = _make_config("http://[::1]:8123")

    with pytest.raises(IPV6NotSupportedError):
        func(config)


@pytest.mark.parametrize(("func"), [build_ws_url, build_rest_url])
def test_no_scheme_raises_exception(func):
    """Test that an exception is raised for URLs without schemes."""
    config = _make_config("example.com", api_port=9123)

    with pytest.raises(SchemeRequiredInBaseUrlError):
        func(config)
