"""URL utilities for constructing Home Assistant API endpoints."""

import typing
from typing import NamedTuple

from yarl import URL

from hassette.exceptions import BaseUrlRequiredError, IPV6NotSupportedError, SchemeRequiredInBaseUrlError

if typing.TYPE_CHECKING:
    from hassette.config.config import HassetteConfig


class BaseUrlParts(NamedTuple):
    """The parts of ``base_url`` that Home Assistant endpoint URLs are built from."""

    scheme: str
    host: str
    port: int | None
    path_prefix: str
    """Decoded path with no trailing slash; ``""`` when base_url has no path or a lone ``/``."""


def _parse_and_normalize_url(config: "HassetteConfig") -> BaseUrlParts:
    """Parse base_url into the parts endpoint URLs are built from.

    Args:
        config: Hassette configuration containing base_url

    Returns:
        The scheme, host, explicit port, and path prefix. Query string and fragment are dropped.

    Raises:
        BaseUrlRequiredError: If base_url is not set in the configuration.
        IPV6NotSupportedError: If base_url contains an IPv6 address.
        SchemeRequiredInBaseUrlError: If base_url does not include a scheme.
    """
    if not config.base_url:
        raise BaseUrlRequiredError(f"base_url must be set in the configuration, got: {config.base_url}")

    if "::" in config.base_url:
        raise IPV6NotSupportedError(f"IPv6 addresses are not supported in base_url, got: {config.base_url}")

    cleaned_url = config.base_url.strip().strip("'\"")
    yurl = URL(cleaned_url)

    if not yurl.scheme:
        raise SchemeRequiredInBaseUrlError(f"base_url must include a scheme (http:// or https://), got: {cleaned_url}")

    if yurl.host is None:
        raise BaseUrlRequiredError(f"base_url must include a valid hostname, got: {cleaned_url}")

    return BaseUrlParts(yurl.scheme, yurl.host, yurl.explicit_port, yurl.path.rstrip("/"))


def _build_ha_url(config: "HassetteConfig", *, ws: bool = False) -> str:
    """Construct a Home Assistant API URL (REST or WebSocket)."""
    parts = _parse_and_normalize_url(config)
    scheme = parts.scheme
    if ws:
        scheme = "wss" if scheme == "https" else "ws"
    path = f"{parts.path_prefix}/api/websocket" if ws else f"{parts.path_prefix}/api/"
    return str(URL.build(scheme=scheme, host=parts.host, port=parts.port, path=path))


def build_ws_url(config: "HassetteConfig") -> str:
    """Construct the WebSocket URL for Home Assistant."""
    return _build_ha_url(config, ws=True)


def build_rest_url(config: "HassetteConfig") -> str:
    """Construct the REST API URL for Home Assistant."""
    return _build_ha_url(config)
