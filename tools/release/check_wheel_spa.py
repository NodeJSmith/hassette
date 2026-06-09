#!/usr/bin/env -S uv run
"""Verify that built wheels contain the SPA frontend assets.

Intended to run in CI after `uv build` and before publishing to PyPI.
Exits non-zero if any wheel in the dist directory is missing the SPA.

Usage:
    python tools/release/check_wheel_spa.py [--dist-dir dist]
"""

import argparse
import sys
import zipfile
from pathlib import Path

REQUIRED_PATTERNS = {
    "index.html": "SPA entry point",
    ".js": "JavaScript bundle",
    ".css": "CSS stylesheet",
}


def check_wheel(wheel_path: Path) -> list[str]:
    with zipfile.ZipFile(wheel_path) as whl:
        spa_files = [n for n in whl.namelist() if "/web/static/spa/" in n]

    if not spa_files:
        return [f"No SPA files at all in {wheel_path.name}"]

    errors = []
    for pattern, description in REQUIRED_PATTERNS.items():
        if not any(f.endswith(pattern) for f in spa_files):
            errors.append(f"Missing {description} ({pattern}) in {wheel_path.name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", default="dist", help="Directory containing built wheels")
    args = parser.parse_args()

    dist = Path(args.dist_dir)
    wheels = list(dist.glob("*.whl"))

    if not wheels:
        print(f"ERROR: No wheels found in {dist}/", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    for wheel in wheels:
        all_errors.extend(check_wheel(wheel))

    if all_errors:
        print("SPA asset check FAILED:", file=sys.stderr)
        for error in all_errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "\nThe frontend must be built before packaging. "
            "Run: npm ci --prefix frontend && npm run build --prefix frontend",
            file=sys.stderr,
        )
        return 1

    print(f"SPA asset check passed: {len(wheels)} wheel(s) verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
