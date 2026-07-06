"""Shared schema-generation logic for schema export and freshness checking.

``scripts/export_schemas.py`` writes the OpenAPI, WebSocket, and config JSON
Schemas to disk. ``tools/check_schemas_fresh.py`` regenerates the same three
schemas in memory and diffs them against the committed files. Both need the
exact same stub Hassette instance and schema-building logic — this module is
the single source of truth so the two callers can't drift apart.
"""

from unittest.mock import MagicMock

from pydantic import TypeAdapter

from hassette.config.config import HassetteConfig
from hassette.web.app import create_fastapi_app
from hassette.web.models import WsServerMessage

CONFIG_SCHEMA_URL = "https://json-schema.org/draft/2020-12/schema"
CONFIG_SCHEMA_TITLE = "Hassette Configuration"
CONFIG_SCHEMA_DESCRIPTION = "Configuration schema for hassette.toml — the Hassette automation framework config file."


def create_stub_hassette() -> MagicMock:
    """Build a MagicMock that satisfies ``create_fastapi_app`` without a live Home Assistant connection."""
    stub = MagicMock()
    stub.config.web_api.cors_origins = ()
    stub.config.web_api.run_ui = False  # no SPA serving needed for schema export
    return stub


def build_config_schema() -> dict:
    """Build the hassette.toml JSON Schema, wrapping HassetteConfig under a ``hassette`` key."""
    raw = HassetteConfig.model_json_schema()
    defs = raw.pop("$defs", {})
    raw.pop("title", None)
    return {
        "$schema": CONFIG_SCHEMA_URL,
        "title": CONFIG_SCHEMA_TITLE,
        "description": CONFIG_SCHEMA_DESCRIPTION,
        "type": "object",
        "properties": {"hassette": raw},
        "$defs": defs,
    }


def build_openapi_schema(stub: MagicMock) -> dict:
    """Create the FastAPI app from ``stub`` and return its OpenAPI schema."""
    app = create_fastapi_app(stub)
    return app.openapi()


def build_ws_schema() -> dict:
    """Return the WsServerMessage Pydantic JSON Schema."""
    adapter = TypeAdapter(WsServerMessage)
    return adapter.json_schema()
