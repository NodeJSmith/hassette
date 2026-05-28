#!/usr/bin/env python3
"""Capture all doc screenshots defined in docs/screenshots.yml.

Usage:
    uv run python scripts/capture_screenshots.py

Requirements:
    - Docker must be running (used by the demo environment for the HA container)
    - Playwright and Chromium must be installed:
          uv run playwright install --with-deps chromium
    - shot-scraper must be installed (dev dependency):
          uv sync --group dev

Flow:
    1. Start the demo environment (HA + hassette + Vite)
    2. Wait for all services to be ready (up to 180 seconds)
    3. Poll until demo_stimulator has generated error data (up to 90 seconds)
    4. Resolve {port} placeholders and inject animation-disabling CSS
    5. Run shot-scraper to capture all screenshots
    6. Tear down the demo environment

Output:
    All docs/_static/web_ui_*.png files defined in docs/screenshots.yml.

Adding a new screenshot:
    Add an entry to docs/screenshots.yml with the URL path, output filename,
    and any selector/javascript needed to set up the UI state.  No changes to
    this script are needed.
"""

import argparse
import atexit
import contextlib
import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import yaml

DEMO_READY_TIMEOUT_SECONDS = 180
ERROR_DATA_TIMEOUT_SECONDS = 90
ERROR_DATA_POLL_INTERVAL_SECONDS = 2
HTTP_SOCKET_TIMEOUT_SECONDS = 5
PROC_WAIT_TIMEOUT_SECONDS = 10

ANIMATION_DISABLE_JS = (
    "const s=document.createElement('style');"
    "s.textContent='*,*::before,*::after{"
    "animation-duration:0s!important;"
    "transition-duration:0s!important;"
    "}';"
    "document.head.appendChild(s);"
)

_demo_proc: "subprocess.Popen[bytes] | None" = None
_tmp_manifest: str | None = None
_torn_down = False


def teardown() -> None:
    """Kill the demo process and remove the temp manifest. Idempotent."""
    global _torn_down
    if _torn_down:
        return
    _torn_down = True

    if _demo_proc is not None:
        try:
            if sys.platform == "win32":
                _demo_proc.terminate()
            else:
                os.killpg(_demo_proc.pid, signal.SIGTERM)
            _demo_proc.wait(timeout=PROC_WAIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                if sys.platform == "win32":
                    _demo_proc.kill()
                else:
                    os.killpg(_demo_proc.pid, signal.SIGKILL)
            with contextlib.suppress(Exception):
                _demo_proc.wait(timeout=PROC_WAIT_TIMEOUT_SECONDS)
        except (ProcessLookupError, OSError):
            pass

    if _tmp_manifest is not None:
        with contextlib.suppress(Exception):
            Path(_tmp_manifest).unlink(missing_ok=True)


def _signal_handler(_signum: int, _frame: object) -> None:
    teardown()
    sys.exit(0)


def main() -> None:
    global _demo_proc, _tmp_manifest

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

    atexit.register(teardown)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    repo_root = Path(__file__).resolve().parent.parent

    manifest_path = repo_root / "docs" / "screenshots.yml"
    with manifest_path.open() as f:
        entries = yaml.safe_load(f)

    if not isinstance(entries, list) or not entries:
        print(f"ERROR: {manifest_path} did not parse to a non-empty list", file=sys.stderr, flush=True)
        sys.exit(1)

    demo_db = repo_root / ".demo-data" / "hassette.db"
    deleted_files: list[str] = []
    for suffix in ("", "-shm", "-wal"):
        db_file = demo_db.with_name(demo_db.name + suffix)
        if db_file.exists():
            db_file.unlink()
            deleted_files.append(db_file.name)
    if deleted_files:
        print(f"Cleaned stale demo DB files: {', '.join(deleted_files)}", flush=True)

    demo_script = repo_root / "scripts" / "hassette_demo.py"
    print("Starting demo environment...", flush=True)
    _demo_proc = subprocess.Popen(
        ["uv", "run", "python", str(demo_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(repo_root),
    )

    demo_output: dict[str, str] = {}
    deadline = time.monotonic() + DEMO_READY_TIMEOUT_SECONDS
    demo_ready = False

    if _demo_proc.stdout is None:
        print("ERROR: Demo process has no stdout pipe", file=sys.stderr, flush=True)
        sys.exit(1)

    line_queue: queue.Queue[bytes | None] = queue.Queue()

    def reader(pipe, out_queue):
        for raw in pipe:
            out_queue.put(raw)
        out_queue.put(None)

    threading.Thread(target=reader, args=(_demo_proc.stdout, line_queue), daemon=True).start()

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                "\nERROR: Demo environment did not become ready within "
                f"{DEMO_READY_TIMEOUT_SECONDS}s.\n"
                "Things to check:\n"
                "  - Is Docker running? (docker info)\n"
                "  - Port conflict? (check demo output above)\n"
                "  - Try running the demo manually: uv run python scripts/hassette_demo.py",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)

        try:
            raw_line = line_queue.get(timeout=min(remaining, 1.0))
        except queue.Empty:
            continue

        if raw_line is None:
            break

        line = raw_line.decode(errors="replace").rstrip()
        print(f"  [demo] {line}", flush=True)

        if line.startswith("DEMO_ERROR="):
            error_msg = line[len("DEMO_ERROR=") :]
            print(f"\nERROR: Demo environment failed to start: {error_msg}", file=sys.stderr, flush=True)
            sys.exit(1)

        if line == "DEMO_READY=true":
            demo_ready = True
            break

        if "=" in line:
            key, _, value = line.partition("=")
            demo_output[key] = value

    if not demo_ready:
        print(
            "\nERROR: Demo process exited unexpectedly before signalling readiness.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)

    frontend_url = demo_output.get("DEMO_FRONTEND_URL", "")
    hassette_url = demo_output.get("DEMO_HASSETTE_URL", "")

    if not frontend_url or not hassette_url:
        print(f"ERROR: Missing URL from demo output. Got: {demo_output}", file=sys.stderr, flush=True)
        sys.exit(1)

    parsed_port = urlparse(frontend_url).port
    if parsed_port is None:
        print(f"ERROR: Could not extract port from DEMO_FRONTEND_URL: {frontend_url}", file=sys.stderr, flush=True)
        sys.exit(1)
    port = str(parsed_port)

    print("Waiting for demo_stimulator error data...", flush=True)
    jobs_url = f"{hassette_url}/api/telemetry/app/demo_stimulator/jobs"
    error_data_deadline = time.monotonic() + ERROR_DATA_TIMEOUT_SECONDS
    error_data_ready = False

    while time.monotonic() < error_data_deadline:
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

    if args.only:
        filters = [f.strip() for f in args.only.split(",")]
        entries = [e for e in entries if any(f in e.get("output", "") for f in filters)]
        if not entries:
            print(f"ERROR: --only {args.only!r} matched no manifest entries", file=sys.stderr, flush=True)
            sys.exit(1)
        print(f"Filtered to {len(entries)} entries matching --only {args.only!r}", flush=True)

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

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yml",
        delete=False,
        prefix="hassette-screenshots-",
    ) as f:
        _tmp_manifest = f.name
        yaml.dump(resolved, f, default_flow_style=False, allow_unicode=True)

    print(f"\nRunning shot-scraper ({len(resolved)} screenshots)...", flush=True)
    shot_result = subprocess.run(
        ["uv", "run", "shot-scraper", "multi", _tmp_manifest],
        cwd=str(repo_root),
    )

    teardown()
    sys.exit(shot_result.returncode)


if __name__ == "__main__":
    main()
