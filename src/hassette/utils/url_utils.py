"""URL utilities for constructing Home Assistant API endpoints."""

import typing

from yarl import URL

if typing.TYPE_CHECKING:
    from hassette.config.core_config import HassetteConfig


def _parse_base_url(config: "HassetteConfig") -> URL:
    """Parse and normalize the base_url into a yarl URL object.

    Ensures the URL has a proper scheme to avoid yarl parsing issues
    with naked hostnames.

    Args:
        config (HassetteConfig): Hassette configuration containing base_url

    Returns:
        URL: Parsed and normalized URL object
    """
    raw = (config.base_url or "").strip()
    if "://" not in raw:
        raw = f"http://{raw}"
    return URL(raw)


def _get_effective_port(config: "HassetteConfig", parsed_url: URL) -> int:
    """Determine the effective port to use for API connections.

    Uses the port from the parsed URL if explicitly set in base_url,
    otherwise falls back to api_port.

    Args:
        config (HassetteConfig): Hassette configuration containing base_url and api_port
        parsed_url (URL): Parsed URL object

    Returns:
        int: Port number to use for connections
    """
    # Check if port was explicitly set in the original base_url
    port_explicitly_set = ":" in config.base_url and config.base_url.split("://", 1)[-1].count(":") > 0
    return parsed_url.port if port_explicitly_set and parsed_url.port is not None else config.api_port


def _get_effective_host(config: "HassetteConfig", parsed_url: URL) -> str:
    """Extract the effective hostname from the parsed URL.

    Falls back to parsing the base_url directly if yarl parsing fails.

    Args:
        config (HassetteConfig): Hassette configuration containing base_url
        parsed_url (URL): Parsed URL object

    Returns:
        str: Hostname to use for connections
    """
    return parsed_url.host or parsed_url.raw_host or (config.base_url.split(":")[0] if config.base_url else "")


def _get_websocket_scheme(http_scheme: str) -> str:
    """Convert HTTP scheme to appropriate WebSocket scheme.

    Args:
        http_scheme (str): HTTP scheme (http, https, etc.)

    Returns:
        str: Corresponding WebSocket scheme (ws or wss)
    """
    return "wss" if http_scheme == "https" else "ws"


def build_ws_url(config: "HassetteConfig") -> str:
    """Construct the WebSocket URL for Home Assistant.

    Args:
        config (HassetteConfig): Hassette configuration containing connection details

    Returns:
        str: Complete WebSocket URL for Home Assistant API
    """
    parsed_url = _parse_base_url(config)
    scheme = _get_websocket_scheme(parsed_url.scheme)
    host = _get_effective_host(config, parsed_url)
    port = _get_effective_port(config, parsed_url)

    return str(URL.build(scheme=scheme, host=host, port=port, path="/api/websocket"))


def build_rest_url(config: "HassetteConfig") -> str:
    """Construct the REST API URL for Home Assistant.

    Args:
        config (HassetteConfig): Hassette configuration containing connection details

    Returns:
        str: Complete REST API URL for Home Assistant API
    """
    parsed_url = _parse_base_url(config)
    scheme = parsed_url.scheme or "http"
    host = _get_effective_host(config, parsed_url)
    port = _get_effective_port(config, parsed_url)

    return str(URL.build(scheme=scheme, host=host, port=port, path="/api/"))
