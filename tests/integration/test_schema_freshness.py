"""Tests that frontend schema files match current backend models.

These tests regenerate ws-schema.json and openapi.json in memory and assert
they match the files on disk. If a test fails, run ``python scripts/export_schemas.py``
to update the schema files.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import TypeAdapter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"


def _create_stub_hassette() -> MagicMock:
    """Minimal mock matching what ``create_fastapi_app`` needs."""
    stub = MagicMock()
    stub.config.web_api_cors_origins = ()
    stub.config.run_web_ui = False
    return stub


class TestSchemaFreshness:
    """Verify that committed schema files match what the backend generates."""

    def test_ws_schema_matches_models(self) -> None:
        from hassette.web.models import WsServerMessage

        adapter = TypeAdapter(WsServerMessage)
        generated = adapter.json_schema()

        schema_path = FRONTEND_DIR / "ws-schema.json"
        assert schema_path.exists(), f"{schema_path} not found — run: python scripts/export_schemas.py"

        on_disk = json.loads(schema_path.read_text())
        assert generated == on_disk, "frontend/ws-schema.json is stale — run: python scripts/export_schemas.py"

    def test_openapi_schema_matches_app(self) -> None:
        from hassette.web.app import create_fastapi_app

        stub = _create_stub_hassette()
        app = create_fastapi_app(stub)
        generated = app.openapi()

        openapi_path = FRONTEND_DIR / "openapi.json"
        assert openapi_path.exists(), f"{openapi_path} not found — run: python scripts/export_schemas.py"

        on_disk = json.loads(openapi_path.read_text())
        assert generated == on_disk, "frontend/openapi.json is stale — run: python scripts/export_schemas.py"

    @pytest.mark.parametrize(
        "msg_type",
        [
            "AppStatusChangedWsMessage",
            "LogWsMessage",
            "ConnectedWsMessage",
            "ConnectivityWsMessage",
            "StateChangedWsMessage",
            "ServiceStatusWsMessage",
        ],
    )
    def test_all_ws_message_types_have_timestamp(self, msg_type: str) -> None:
        """Every WS message type must include 'timestamp' in its required fields."""
        from hassette.web.models import WsServerMessage

        adapter = TypeAdapter(WsServerMessage)
        schema = adapter.json_schema()

        msg_schema = schema["$defs"][msg_type]
        assert "timestamp" in msg_schema.get("required", []), f"{msg_type} is missing 'timestamp' in required fields"
