#!/usr/bin/env python3
"""Verify that a published wheel on PyPI contains SPA frontend assets.

Downloads the wheel for a given version from PyPI and checks for the
same assets as check_wheel_spa.py. Intended for post-publish verification.

Usage:
    python tools/check_pypi_wheel.py --version 0.38.0
    python tools/check_pypi_wheel.py --version 0.38.0 --timeout 120 --poll-interval 30
"""

import argparse
import io
import json
import sys
import time
import urllib.request
import zipfile

PYPI_PROJECT_URL = "https://pypi.org/pypi/hassette"
POLL_ATTEMPTS = 5
POLL_INTERVAL_SECONDS = 30
INITIAL_WAIT_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 15
DOWNLOAD_TIMEOUT_SECONDS = 60

REQUIRED_ASSETS = {
    "index.html": "SPA entry point",
    ".js": "JavaScript bundle",
    ".css": "CSS stylesheet",
}


def wait_for_version(version: str) -> dict:
    url = f"{PYPI_PROJECT_URL}/{version}/json"

    for attempt in range(POLL_ATTEMPTS):
        try:
            resp = urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECONDS)  # noqa: S310
            return json.loads(resp.read())
        except Exception:
            if attempt == POLL_ATTEMPTS - 1:
                print(f"::error::Package hassette {version} not found on PyPI after {POLL_ATTEMPTS} attempts")
                sys.exit(1)
            print(f"Not available yet (attempt {attempt + 1}/{POLL_ATTEMPTS}), waiting {POLL_INTERVAL_SECONDS}s...")
            time.sleep(POLL_INTERVAL_SECONDS)

    sys.exit(1)


def verify_wheel(data: dict, version: str) -> int:
    wheel_url = next((f["url"] for f in data["urls"] if f["filename"].endswith(".whl")), None)
    if not wheel_url:
        print(f"::error::No wheel found on PyPI for hassette {version}")
        return 1

    print("Downloading wheel from PyPI...")
    whl_data = urllib.request.urlopen(wheel_url, timeout=DOWNLOAD_TIMEOUT_SECONDS).read()  # noqa: S310
    whl = zipfile.ZipFile(io.BytesIO(whl_data))

    spa_files = [n for n in whl.namelist() if "/web/static/spa/" in n]
    if not spa_files:
        print("::error::CRITICAL: Published wheel is missing SPA frontend assets!")
        print("The package was uploaded without the frontend build.")
        return 1

    missing = []
    for pattern, description in REQUIRED_ASSETS.items():
        if not any(f.endswith(pattern) for f in spa_files):
            missing.append(f"{description} ({pattern})")

    if missing:
        print(f"::error::SPA missing required assets: {missing}")
        return 1

    print(f"PyPI smoke test passed: {len(spa_files)} SPA assets verified in published wheel")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Version to check (without 'v' prefix)")
    args = parser.parse_args()

    print(f"Waiting {INITIAL_WAIT_SECONDS}s for PyPI to propagate v{args.version}...")
    time.sleep(INITIAL_WAIT_SECONDS)

    data = wait_for_version(args.version)
    return verify_wheel(data, args.version)


if __name__ == "__main__":
    raise SystemExit(main())
