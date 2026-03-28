#!/usr/bin/env -S uv run
"""Pre-push hook: verify frontend schema files match current backend models.

Regenerates openapi.json and ws-schema.json in memory and compares against the
committed files. Fails with a non-zero exit code if they differ, printing the
command to fix it.

This catches the common mistake of modifying a route/model and forgetting to
run ``python scripts/export_schemas.py`` before pushing.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _create_stub_hassette() -> MagicMock:
    stub = MagicMock()
    stub.config.web_api_cors_origins = ()
    stub.config.run_web_ui = False
    return stub


def main() -> int:
    from pydantic import TypeAdapter

    from hassette.web.app import create_fastapi_app
    from hassette.web.models import WsServerMessage

    repo_root = Path(__file__).resolve().parent.parent
    frontend_dir = repo_root / "frontend"
    stale: list[str] = []

    # Check openapi.json
    stub = _create_stub_hassette()
    app = create_fastapi_app(stub)
    generated_openapi = app.openapi()
    openapi_path = frontend_dir / "openapi.json"
    if openapi_path.exists():
        on_disk = json.loads(openapi_path.read_text())
        if generated_openapi != on_disk:
            stale.append(str(openapi_path.relative_to(repo_root)))
    else:
        stale.append(str(openapi_path.relative_to(repo_root)))

    # Check ws-schema.json
    adapter = TypeAdapter(WsServerMessage)
    generated_ws = adapter.json_schema()
    ws_path = frontend_dir / "ws-schema.json"
    if ws_path.exists():
        on_disk = json.loads(ws_path.read_text())
        if generated_ws != on_disk:
            stale.append(str(ws_path.relative_to(repo_root)))
    else:
        stale.append(str(ws_path.relative_to(repo_root)))

    if stale:
        print(f"Stale schema files: {', '.join(stale)}")
        print("Run: python scripts/export_schemas.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
