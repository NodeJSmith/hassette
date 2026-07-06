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

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from schema_helpers import build_config_schema, build_openapi_schema, build_ws_schema, create_stub_hassette  # noqa: E402,I001


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
    frontend_dir = REPO_ROOT / "frontend"
    stale: list[str] = []

    # Check hassette.schema.json (config schema)
    generated_config = build_config_schema()
    config_path = REPO_ROOT / "hassette.schema.json"
    if result := _check_file(REPO_ROOT, config_path, generated_config):
        stale.append(result)

    # Check openapi.json
    stub = create_stub_hassette()
    generated_openapi = build_openapi_schema(stub)
    openapi_path = frontend_dir / "openapi.json"
    if result := _check_file(REPO_ROOT, openapi_path, generated_openapi):
        stale.append(result)

    # Check ws-schema.json
    generated_ws = build_ws_schema()
    ws_path = frontend_dir / "ws-schema.json"
    if result := _check_file(REPO_ROOT, ws_path, generated_ws):
        stale.append(result)

    if stale:
        print(f"Stale schema files: {', '.join(stale)}")
        print("Run: python scripts/export_schemas.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
