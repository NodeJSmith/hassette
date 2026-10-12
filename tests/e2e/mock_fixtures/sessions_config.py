"""Config wiring for e2e mock data."""

from unittest.mock import MagicMock

from hassette.config import HassetteConfig
from hassette.config.models import DEFAULT_WEB_API_PORT


def wire_config(hassette: MagicMock, *, auth_enabled: bool = False) -> None:
    """Wire a real HassetteConfig on mock_hassette so GET /config works.

    The /config route serializes the live config with ``hassette.config.model_dump(mode="json")``
    to build the values half of its schema-driven view. A SimpleNamespace has no ``model_dump``,
    so the route would 500 and the schema view would never render. The stub must therefore be a
    real ``HassetteConfig`` instance. (The schema half comes from ``HassetteConfig.model_json_schema()``,
    a classmethod, so it never needed the instance.)

    The explicit kwargs pin the values that would otherwise drift across environments:
    ``dev_mode=False`` (the default ``get_dev_mode()`` returns True when a debugger is attached),
    and ``web_api`` host/port so those value cells stay stable. ``auth_enabled`` must be forwarded
    from the caller's own ``auth_enabled`` choice (default ``False``) -- this replaces the whole
    ``hassette.config`` object with a real ``HassetteConfig``, and ``WebApiConfig.auth_enabled``
    defaults to ``True``, so omitting it here silently re-enables the default-deny middleware for
    every caller that asked for ``auth_enabled=False``.
    """
    hassette.config = HassetteConfig(
        token="e2e-test-token",
        dev_mode=False,
        web_api={"host": "0.0.0.0", "port": DEFAULT_WEB_API_PORT, "auth_enabled": auth_enabled},
    )
