"""URL utilities for constructing Home Assistant API endpoints."""

import typing
from urllib.parse import urlparse

if typing.TYPE_CHECKING:
    from hassette.config.core_config import HassetteConfig


def _parse_and_normalize_url(config: "HassetteConfig") -> tuple[str, str, int]:
    """Parse base_url and extract normalized components.

    Args:
        config (HassetteConfig): Hassette configuration containing base_url and api_port

    Returns:
        tuple[str, str, int]: (scheme, hostname, port)
    """
    base_url = (config.base_url or "").strip()

    # Ensure URL has a scheme for proper parsing
    if "://" not in base_url:
        base_url = f"http://{base_url}"

    parsed = urlparse(base_url)

    # Extract scheme, defaulting to http
    scheme = parsed.scheme or "http"

    # Extract hostname
    hostname = parsed.hostname or base_url.split("://")[-1].split(":")[0]

    # Determine effective port: use URL port if specified, otherwise api_port
    port = parsed.port if parsed.port is not None else config.api_port

    return scheme, hostname, port


def build_ws_url(config: "HassetteConfig") -> str:
    """Construct the WebSocket URL for Home Assistant.

    Args:
        config (HassetteConfig): Hassette configuration containing connection details

    Returns:
        str: Complete WebSocket URL for Home Assistant API
    """
    scheme, hostname, port = _parse_and_normalize_url(config)

    # Convert HTTP scheme to WebSocket scheme
    ws_scheme = "wss" if scheme == "https" else "ws"

    return f"{ws_scheme}://{hostname}:{port}/api/websocket"


def build_rest_url(config: "HassetteConfig") -> str:
    """Construct the REST API URL for Home Assistant.

    Args:
        config (HassetteConfig): Hassette configuration containing connection details

    Returns:
        str: Complete REST API URL for Home Assistant API
    """
    scheme, hostname, port = _parse_and_normalize_url(config)

    return f"{scheme}://{hostname}:{port}/api/"
