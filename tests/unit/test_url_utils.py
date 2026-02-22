"""Comprehensive tests for URL utility functions."""

import pytest

from hassette.config.config import HassetteConfig
from hassette.exceptions import BaseUrlRequiredError, IPV6NotSupportedError, SchemeRequiredInBaseUrlError
from hassette.utils.url_utils import _parse_and_normalize_url, build_rest_url, build_ws_url


def _make_config(base_url: str, api_port: int = 8123) -> HassetteConfig:
    """Create a test configuration with the given base_url and api_port."""
    config = HassetteConfig.model_construct(_fields_set=set())
    config.token = "test-token"
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

    assert build_ws_url(config) == "wss://example.com/api/websocket"
    assert build_rest_url(config) == "https://example.com/api/"


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
    ("input_url", "expected_port"),
    [
        ("http://test.local", None),
        ("https://test.local", None),
        ("http://192.168.1.1", None),
        ("http://localhost:8000", 8000),
        ("http://127.0.0.1:8000", 8000),
    ],
)
def test_no_port_added_if_not_provided(input_url: str, expected_port: int | None):
    """Test that no port is added if not provided in the URL."""
    config = _make_config(input_url)

    _, _, port = _parse_and_normalize_url(config)

    assert port == expected_port


@pytest.mark.parametrize(
    ("input_url", "expected_ws_scheme", "expected_rest_scheme"),
    [
        ("http://test.local", "ws", "http"),
        ("https://test.local", "wss", "https"),
        ("ftp://test.local", "ws", "ftp"),  # Non-standard scheme
    ],
)
def test_scheme_conversion_parametrized(input_url: str, expected_ws_scheme: str, expected_rest_scheme: str):
    """Test scheme conversion with various input schemes."""
    config = _make_config(input_url)

    ws_url = build_ws_url(config)
    rest_url = build_rest_url(config)

    assert ws_url.startswith(f"{expected_ws_scheme}://")
    assert rest_url.startswith(f"{expected_rest_scheme}://")


@pytest.mark.parametrize(("func"), [build_ws_url, build_rest_url])
def test_config_with_empty_base_url_raises(func):
    """Test that an exception is raised for URLs without schemes."""
    config = _make_config("")

    with pytest.raises(BaseUrlRequiredError):
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


@pytest.mark.parametrize(
    ("input_url", "expected_scheme", "expected_host", "expected_port"),
    [
        ('"http://homeassistant:8123"', "http", "homeassistant", 8123),
        ("'http://homeassistant:8123'", "http", "homeassistant", 8123),
        ('" http://homeassistant:8123 "', "http", "homeassistant", 8123),
        ("' http://homeassistant:8123 '", "http", "homeassistant", 8123),
        ('"https://example.com"', "https", "example.com", None),
        ("'https://example.com'", "https", "example.com", None),
    ],
)
def test_quoted_urls_are_stripped(input_url: str, expected_scheme: str, expected_host: str, expected_port: int | None):
    """Test that literal quote characters wrapping a URL are stripped before parsing."""
    config = _make_config(input_url)

    scheme, host, port = _parse_and_normalize_url(config)

    assert scheme == expected_scheme
    assert host == expected_host
    assert port == expected_port
