"""URL utilities for constructing Home Assistant API endpoints."""

import typing

from yarl import URL

from hassette.exceptions import BaseUrlRequiredError, IPV6NotSupportedError, SchemeRequiredInBaseUrlError

if typing.TYPE_CHECKING:
    from hassette.config.config import HassetteConfig


def _parse_and_normalize_url(config: "HassetteConfig") -> tuple[str, str, int | None]:
    """Parse base_url and extract normalized components.

    Args:
        config: Hassette configuration containing base_url and api_port

    Returns:
        schema, hostname, and port

    Raises:
        BaseUrlRequiredError: If base_url is not set in the configuration.
        IPV6NotSupportedError: If base_url contains an IPv6 address.
        SchemeRequiredInBaseUrlError: If base_url does not include a scheme.
    """

    if not config.base_url:
        raise BaseUrlRequiredError(f"base_url must be set in the configuration, got: {config.base_url}")

    if "::" in config.base_url:
        raise IPV6NotSupportedError(f"IPv6 addresses are not supported in base_url, got: {config.base_url}")

    yurl = URL(config.base_url.strip())

    if not yurl.scheme:
        raise SchemeRequiredInBaseUrlError(
            f"base_url must include a scheme (http:// or https://), got: {config.base_url}"
        )

    if yurl.host is None:
        raise BaseUrlRequiredError(f"base_url must include a valid hostname, got: {config.base_url}")

    return yurl.scheme, yurl.host, yurl.explicit_port


def build_ws_url(config: "HassetteConfig") -> str:
    """Construct the WebSocket URL for Home Assistant.

    Args:
        config: Hassette configuration containing connection details

    Returns:
        Complete WebSocket URL for Home Assistant API
    """
    scheme, hostname, port = _parse_and_normalize_url(config)

    # Convert HTTP scheme to WebSocket scheme
    ws_scheme = "wss" if scheme == "https" else "ws"

    yurl = URL.build(scheme=ws_scheme, host=hostname, port=port, path="/api/websocket")
    return str(yurl)


def build_rest_url(config: "HassetteConfig") -> str:
    """Construct the REST API URL for Home Assistant.

    Args:
        config: Hassette configuration containing connection details

    Returns:
        Complete REST API URL for Home Assistant API
    """
    scheme, hostname, port = _parse_and_normalize_url(config)

    yurl = URL.build(scheme=scheme, host=hostname, port=port, path="/api/")

    return str(yurl)
