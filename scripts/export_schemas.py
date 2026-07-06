#!/usr/bin/env python3
"""Export JSON Schemas for frontend type generation and config validation.

Creates a minimal Hassette stub (no Home Assistant connection required) to
extract the FastAPI OpenAPI schema and the WsServerMessage Pydantic JSON
Schema.  Also exports the HassetteConfig JSON Schema for IDE autocompletion
and SchemaStore publication.

Outputs:

- ``frontend/openapi.json``  — for ``openapi-typescript``
- ``frontend/ws-schema.json`` — for ``generate-ws-types.cjs``
- ``hassette.schema.json``   — for IDE/SchemaStore TOML validation

Usage::

    python scripts/export_schemas.py
    python scripts/export_schemas.py --types  # also generates TypeScript types
"""

import argparse
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from pydantic import TypeAdapter

# Bootstrap a minimal FastAPI app without connecting to Home Assistant


def _create_stub_hassette() -> MagicMock:
    """Build a MagicMock that satisfies ``create_fastapi_app``."""
    stub = MagicMock()
    stub.config.web_api.cors_origins = ()
    stub.config.web_api.run_ui = False  # no SPA serving needed for schema export
    return stub


def _build_config_schema() -> dict:
    """Build the hassette.toml JSON Schema wrapping HassetteConfig under a ``hassette`` key."""
    from hassette.config.config import HassetteConfig  # lazy-import: defers heavy config import to call time

    raw = HassetteConfig.model_json_schema()
    defs = raw.pop("$defs", {})
    raw.pop("title", None)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Hassette Configuration",
        "description": "Configuration schema for hassette.toml — the Hassette automation framework config file.",
        "type": "object",
        "properties": {
            "hassette": raw,
        },
        "$defs": defs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export OpenAPI, WebSocket, and config JSON Schemas.")
    parser.add_argument(
        "--types",
        action="store_true",
        help="Also run openapi-typescript to generate frontend/src/api/generated-types.ts",
    )
    args = parser.parse_args()

    from hassette.web.app import create_fastapi_app  # lazy-import: defers heavy hassette.web app import to call time
    from hassette.web.models import WsServerMessage  # lazy-import: defers heavy hassette.web app import to call time

    repo_root = Path(__file__).resolve().parent.parent
    frontend_dir = repo_root / "frontend"
    frontend_dir.mkdir(exist_ok=True)

    # Config schema (hassette.toml)
    config_schema = _build_config_schema()
    config_schema_path = repo_root / "hassette.schema.json"
    config_schema_path.write_text(json.dumps(config_schema, indent=2) + "\n")
    print(f"Wrote {config_schema_path}")

    # OpenAPI schema
    stub = _create_stub_hassette()
    app = create_fastapi_app(stub)
    openapi = app.openapi()
    openapi_path = frontend_dir / "openapi.json"
    openapi_path.write_text(json.dumps(openapi, indent=2) + "\n")
    print(f"Wrote {openapi_path}")

    # WebSocket message schema
    adapter = TypeAdapter(WsServerMessage)
    ws_schema = adapter.json_schema()

    ws_schema_path = frontend_dir / "ws-schema.json"
    ws_schema_path.write_text(json.dumps(ws_schema, indent=2) + "\n")
    print(f"Wrote {ws_schema_path}")

    # TypeScript types (optional)
    if args.types:
        scripts_dir = repo_root / "scripts"

        print("Running openapi-typescript...")
        try:
            subprocess.run(
                ["npx", "openapi-typescript", "openapi.json", "-o", "src/api/generated-types.ts"],
                cwd=frontend_dir,
                check=True,
            )
        except FileNotFoundError as exc:
            raise SystemExit("openapi-typescript not found — run `npm ci` in the frontend directory first") from exc
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                f"openapi-typescript failed (exit {exc.returncode})"
                " — run `npm ci` in the frontend directory if dependencies are missing"
            ) from exc
        generated_path = frontend_dir / "src" / "api" / "generated-types.ts"
        print(f"Wrote {generated_path}")

        print("Running generate-ws-types...")
        try:
            subprocess.run(
                ["node", str(scripts_dir / "generate-ws-types.cjs")],
                cwd=frontend_dir,
                check=True,
            )
        except FileNotFoundError as exc:
            raise SystemExit("node not found — Node.js is required for WS type generation") from exc
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                f"generate-ws-types.cjs failed (exit {exc.returncode})"
                " — run `npm ci` in the frontend directory if dependencies are missing"
            ) from exc


if __name__ == "__main__":
    main()
