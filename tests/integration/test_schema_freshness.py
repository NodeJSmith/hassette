"""Tests that schema files match current backend models.

These tests regenerate ws-schema.json, openapi.json, and hassette.schema.json
in memory and assert they match the files on disk. If a test fails, run
``python scripts/export_schemas.py`` to update the schema files.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
FRONTEND_DIR = REPO_ROOT / "frontend"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from pydantic import TypeAdapter  # noqa: E402
from schema_helpers import (  # noqa: E402
    build_config_schema,
    build_openapi_schema,
    build_ws_schema,
    create_stub_hassette,
)

from hassette.web.models import WsServerMessage  # noqa: E402


class TestSchemaFreshness:
    """Verify that committed schema files match what the backend generates."""

    def test_ws_schema_matches_models(self) -> None:
        generated = build_ws_schema()

        schema_path = FRONTEND_DIR / "ws-schema.json"
        assert schema_path.exists(), f"{schema_path} not found — run: python scripts/export_schemas.py"

        on_disk = json.loads(schema_path.read_text())
        assert generated == on_disk, "frontend/ws-schema.json is stale — run: python scripts/export_schemas.py"

    def test_config_schema_matches_model(self) -> None:
        generated = build_config_schema()

        schema_path = REPO_ROOT / "hassette.schema.json"
        assert schema_path.exists(), f"{schema_path} not found — run: python scripts/export_schemas.py"

        on_disk = json.loads(schema_path.read_text())
        assert generated == on_disk, "hassette.schema.json is stale — run: python scripts/export_schemas.py"

    def test_openapi_schema_matches_app(self) -> None:
        stub = create_stub_hassette()
        generated = build_openapi_schema(stub)

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
            "ExecutionCompletedWsMessage",
        ],
    )
    def test_all_ws_message_types_have_timestamp(self, msg_type: str) -> None:
        """Every WS message type must include 'timestamp' in its required fields."""
        adapter = TypeAdapter(WsServerMessage)
        schema = adapter.json_schema()

        msg_schema = schema["$defs"][msg_type]
        assert "timestamp" in msg_schema.get("required", []), f"{msg_type} is missing 'timestamp' in required fields"

    def test_execution_completed_has_kind_field(self) -> None:
        """ExecutionCompletedData must include 'kind' in its required fields."""
        adapter = TypeAdapter(WsServerMessage)
        schema = adapter.json_schema()

        data_schema = schema["$defs"]["ExecutionCompletedData"]
        assert "kind" in data_schema.get("required", []), "ExecutionCompletedData is missing required 'kind' field"
