#!/usr/bin/env -S uv run
"""Pre-push hook: verify schema files match current backend models.

Regenerates openapi.json, ws-schema.json, and hassette.schema.json in memory
and compares against the committed files. Fails with a non-zero exit code if
they differ, printing the command to fix it.

This catches the common mistake of modifying a route/model/config and
forgetting to run ``python scripts/export_schemas.py`` before pushing.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

from pydantic import TypeAdapter


def _create_stub_hassette() -> MagicMock:
    stub = MagicMock()
    stub.config.web_api.cors_origins = ()
    stub.config.web_api.run_ui = False
    return stub


def _check_file(repo_root: Path, path: Path, generated: dict) -> str | None:
    """Return the relative path if the on-disk file is stale or missing, else None."""
    if path.exists():
        on_disk = json.loads(path.read_text())
        if generated != on_disk:
            return str(path.relative_to(repo_root))
    else:
        return str(path.relative_to(repo_root))
    return None


def main() -> int:
    from hassette.web.app import create_fastapi_app  # lazy-import: defers heavy hassette.web app import to call time
    from hassette.web.models import WsServerMessage  # lazy-import: defers heavy hassette.web app import to call time

    repo_root = Path(__file__).resolve().parent.parent
    frontend_dir = repo_root / "frontend"
    stale: list[str] = []

    # Check hassette.schema.json (config schema)
    from hassette.config.config import HassetteConfig  # lazy-import: defers heavy config import to call time

    raw_config = HassetteConfig.model_json_schema()
    defs = raw_config.pop("$defs", {})
    raw_config.pop("title", None)
    generated_config = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Hassette Configuration",
        "description": "Configuration schema for hassette.toml — the Hassette automation framework config file.",
        "type": "object",
        "properties": {"hassette": raw_config},
        "$defs": defs,
    }
    config_path = repo_root / "hassette.schema.json"
    if result := _check_file(repo_root, config_path, generated_config):
        stale.append(result)

    # Check openapi.json
    stub = _create_stub_hassette()
    app = create_fastapi_app(stub)
    generated_openapi = app.openapi()
    openapi_path = frontend_dir / "openapi.json"
    if result := _check_file(repo_root, openapi_path, generated_openapi):
        stale.append(result)

    # Check ws-schema.json
    adapter = TypeAdapter(WsServerMessage)
    generated_ws = adapter.json_schema()
    ws_path = frontend_dir / "ws-schema.json"
    if result := _check_file(repo_root, ws_path, generated_ws):
        stale.append(result)

    if stale:
        print(f"Stale schema files: {', '.join(stale)}")
        print("Run: python scripts/export_schemas.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
