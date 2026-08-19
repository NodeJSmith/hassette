"""Session list and config builders/wiring for e2e mock data."""

from unittest.mock import AsyncMock, MagicMock

from hassette.config import HassetteConfig
from hassette.config.models import DEFAULT_WEB_API_PORT
from hassette.schemas.summary_models import SessionRecord
from tests.e2e.mock_fixtures.constants import TS_BASE


def build_session_list() -> list[SessionRecord]:
    """Build session records for the sessions page."""
    return [
        SessionRecord(
            id=1,
            started_at=TS_BASE,
            stopped_at=None,
            status="running",
            error_type=None,
            error_message=None,
            duration_seconds=3600.0,
        ),
        SessionRecord(
            id=2,
            started_at=1704060000.0,
            stopped_at=1704063600.0,
            status="success",
            error_type=None,
            error_message=None,
            duration_seconds=3600.0,
        ),
        SessionRecord(
            id=3,
            started_at=1704050000.0,
            stopped_at=1704053600.0,
            status="failure",
            error_type="RuntimeError",
            error_message="WebSocket connection lost",
            duration_seconds=3600.0,
        ),
    ]


def wire_session_telemetry(hassette, sessions: list[SessionRecord]) -> None:
    """Wire session list onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_session_list = AsyncMock(return_value=sessions)


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
