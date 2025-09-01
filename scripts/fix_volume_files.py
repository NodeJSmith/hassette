#!/usr/bin/env -S uv run --script

import json
from pathlib import Path


def fix_files():
    auth_path = Path("volumes/config/.storage/auth")
    contents = auth_path.read_text()
    if contents[-1] != "\n":
        with auth_path.open("+a") as f:
            f.write("\n")

    http_path = Path("volumes/config/.storage/http")
    contents = json.loads(http_path.read_text())
    http_path.write_text(json.dumps(contents, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    fix_files()
