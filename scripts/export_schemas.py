#!/usr/bin/env python3
"""Export OpenAPI and WebSocket JSON Schemas for frontend type generation.

Creates a minimal Hassette stub (no Home Assistant connection required) to
extract the FastAPI OpenAPI schema and the WsServerMessage Pydantic JSON
Schema.  Outputs:

- ``frontend/openapi.json``  — for ``openapi-typescript``
- ``frontend/ws-schema.json`` — for CI conformance testing of hand-authored
  TypeScript WS types

Usage::

    python scripts/export_schemas.py
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Bootstrap a minimal FastAPI app without connecting to Home Assistant
# ---------------------------------------------------------------------------


def _create_stub_hassette() -> MagicMock:
    """Build a MagicMock that satisfies ``create_fastapi_app``."""
    stub = MagicMock()
    stub.config.web_api_cors_origins = ()
    stub.config.run_web_ui = False  # no SPA serving needed for schema export
    return stub


def main() -> None:
    from hassette.web.app import create_fastapi_app
    from hassette.web.models import WsServerMessage

    repo_root = Path(__file__).resolve().parent.parent
    frontend_dir = repo_root / "frontend"
    frontend_dir.mkdir(exist_ok=True)

    # --- OpenAPI schema ---
    stub = _create_stub_hassette()
    app = create_fastapi_app(stub)
    openapi = app.openapi()
    openapi_path = frontend_dir / "openapi.json"
    openapi_path.write_text(json.dumps(openapi, indent=2) + "\n")
    print(f"Wrote {openapi_path}")

    # --- WebSocket message schema ---
    from pydantic import TypeAdapter

    adapter = TypeAdapter(WsServerMessage)
    ws_schema = adapter.json_schema()

    ws_schema_path = frontend_dir / "ws-schema.json"
    ws_schema_path.write_text(json.dumps(ws_schema, indent=2) + "\n")
    print(f"Wrote {ws_schema_path}")


if __name__ == "__main__":
    main()
