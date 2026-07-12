#!/usr/bin/env python3
"""Capture all doc screenshots defined in docs/screenshots.yml.

Usage:
    uv run python scripts/capture_screenshots.py

Requirements:
    - Docker must be running (used by the demo stack for HA + hassette + Vite)
    - Playwright and Chromium must be installed:
          uv run playwright install --with-deps chromium
    - shot-scraper must be installed (dev dependency):
          uv sync --group dev

Flow:
    1. Delete stale demo DB files
    2. Start the demo stack (HA + hassette + Vite) via DemoStack
    3. Poll until demo_stimulator has generated error data (up to 90 seconds)
    4. Resolve {port} placeholders and inject animation-disabling CSS
    5. Run shot-scraper to capture all screenshots
    6. Tear down the demo stack

Output:
    All docs/_static/web_ui_*.png files defined in docs/screenshots.yml.

Adding a new screenshot:
    Add an entry to docs/screenshots.yml with the URL path, output filename,
    and any selector/javascript needed to set up the UI state.  No changes to
    this script are needed.
"""

import argparse
import contextlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from demo_stack import DemoStack

ERROR_DATA_TIMEOUT_SECONDS = 90
ERROR_DATA_POLL_INTERVAL_SECONDS = 2
HTTP_SOCKET_TIMEOUT_SECONDS = 5

ANIMATION_DISABLE_JS = (
    "const s=document.createElement('style');"
    "s.textContent='*,*::before,*::after{"
    "animation-duration:0s!important;"
    "transition-duration:0s!important;"
    "}';"
    "document.head.appendChild(s);"
)


def _clean_stale_demo_db(repo_root: Path) -> None:
    """Delete leftover demo DB files from a previous run so telemetry starts fresh."""
    demo_db = repo_root / ".demo-data" / "hassette.db"
    deleted_files: list[str] = []
    for suffix in ("", "-shm", "-wal"):
        db_file = demo_db.with_name(demo_db.name + suffix)
        if db_file.exists():
            db_file.unlink()
            deleted_files.append(db_file.name)
    if deleted_files:
        print(f"Cleaned stale demo DB files: {', '.join(deleted_files)}", flush=True)


def _wait_for_error_data(hassette_port: int) -> None:
    """Poll until demo_stimulator has produced at least one failed job.

    Soft failure: prints a warning and returns instead of exiting, since
    error-state screenshots being empty is not fatal to the whole run.
    """
    print("Waiting for demo_stimulator error data...", flush=True)
    jobs_url = f"http://localhost:{hassette_port}/api/telemetry/app/demo_stimulator/jobs"
    deadline = time.monotonic() + ERROR_DATA_TIMEOUT_SECONDS
    error_data_ready = False

    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(jobs_url)
            with urllib.request.urlopen(req, timeout=HTTP_SOCKET_TIMEOUT_SECONDS) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read())
                    if isinstance(data, list) and any(
                        isinstance(entry, dict) and entry.get("failed", 0) > 0 for entry in data
                    ):
                        error_data_ready = True
                        break
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(ERROR_DATA_POLL_INTERVAL_SECONDS)

    if not error_data_ready:
        print(
            f"WARNING: demo_stimulator error data not ready within {ERROR_DATA_TIMEOUT_SECONDS}s. "
            "Error-state screenshots may be empty.",
            file=sys.stderr,
            flush=True,
        )


def _resolve_manifest(entries: list[object], port: str) -> list[dict[str, object]]:
    """Replace {port} placeholders and prepend the animation-disabling JS."""
    resolved: list[dict[str, object]] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            print(f"ERROR: Manifest entry {i} is not a dict: {type(entry).__name__}", file=sys.stderr, flush=True)
            sys.exit(1)
        url = entry.get("url")
        if not isinstance(url, str):
            print(f"ERROR: Manifest entry {i} has invalid 'url': {url!r}", file=sys.stderr, flush=True)
            sys.exit(1)
        e = dict(entry)
        e["url"] = url.replace("{port}", port)
        existing_js = e.get("javascript") or ""
        e["javascript"] = ANIMATION_DISABLE_JS + str(existing_js)
        resolved.append(e)
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--only",
        help="Comma-separated substrings to match against output filenames. "
        "Only matching entries are captured. Example: --only column_picker,sidebar",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    manifest_path = repo_root / "docs" / "screenshots.yml"
    with manifest_path.open() as f:
        entries = yaml.safe_load(f)

    if not isinstance(entries, list) or not entries:
        print(f"ERROR: {manifest_path} did not parse to a non-empty list", file=sys.stderr, flush=True)
        sys.exit(1)

    _clean_stale_demo_db(repo_root)

    print("Starting demo stack...", flush=True)
    with DemoStack() as demo:
        _wait_for_error_data(demo.hassette_port)

        if args.only:
            filters = [f.strip() for f in args.only.split(",")]
            entries = [e for e in entries if any(f in e.get("output", "") for f in filters)]
            if not entries:
                print(f"ERROR: --only {args.only!r} matched no manifest entries", file=sys.stderr, flush=True)
                sys.exit(1)
            print(f"Filtered to {len(entries)} entries matching --only {args.only!r}", flush=True)

        resolved = _resolve_manifest(entries, str(demo.vite_port))

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yml",
            delete=False,
            prefix="hassette-screenshots-",
        ) as tmp_manifest:
            yaml.dump(resolved, tmp_manifest, default_flow_style=False, allow_unicode=True)
            tmp_manifest_path = tmp_manifest.name

        try:
            print(f"\nRunning shot-scraper ({len(resolved)} screenshots)...", flush=True)
            shot_result = subprocess.run(
                ["uv", "run", "shot-scraper", "multi", tmp_manifest_path],
                cwd=str(repo_root),
            )
        finally:
            with contextlib.suppress(Exception):
                Path(tmp_manifest_path).unlink(missing_ok=True)

    sys.exit(shot_result.returncode)


if __name__ == "__main__":
    main()
