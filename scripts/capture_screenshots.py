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
    5. Mint a session cookie for the demo auth token and save it as Playwright
       storage state (see _mint_auth_storage_state)
    6. Run shot-scraper twice: once with that storage state for every
       authenticated page, once with no auth for pages marked
       `unauthenticated: true` in the manifest (currently only /login)
    7. Tear down the demo stack

Output:
    All docs/_static/web_ui_*.png files defined in docs/screenshots.yml.

Adding a new screenshot:
    Add an entry to docs/screenshots.yml with the URL path, output filename,
    and any selector/javascript needed to set up the UI state.  No changes to
    this script are needed.
"""

import argparse
import contextlib
import http.cookies
import json
import shutil
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
SCREENSHOT_CAPTURE_TIMEOUT_SECONDS = 600
DEFAULT_SESSION_MAX_AGE_SECONDS = 3600  # WebApiConfig.session_ttl's own default, used only if a
# Set-Cookie response is somehow missing Max-Age

# Must match HASSETTE__WEB_API__AUTH_TOKEN in scripts/docker/ha-demo.yml
DEMO_AUTH_TOKEN = "demo-token"

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
            try:
                db_file.unlink()
            except PermissionError:
                # Pre-existing root-owned files from before the non-root container fix
                print(
                    f"WARNING: cannot delete root-owned {db_file.name} — run: sudo rm -rf {repo_root / '.demo-data'}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
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
            req = urllib.request.Request(jobs_url, headers={"Authorization": f"Bearer {DEMO_AUTH_TOKEN}"})
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


def _mint_auth_storage_state(hassette_port: int) -> dict[str, object]:
    """Exchange the demo auth token for a session cookie and shape it as Playwright storage state.

    shot-scraper's ``--auth`` flag loads its argument file's JSON directly as Playwright's
    ``storage_state`` context argument (``shot_scraper.cli._browser_context``), so building that
    JSON here authenticates every subsequent page load with no browser-driven login.

    The cookie's domain is pinned to bare ``localhost`` rather than the Vite dev server's port —
    cookies are not port-scoped, and every doc screenshot is captured against
    ``http://localhost:{vite_port}``, which Vite proxies to hassette server-side (see
    ``VITE_PROXY_TARGET`` in ``scripts/docker/ha-demo.yml``) — so the browser only ever talks to
    one origin, ``localhost``, regardless of which port is behind it.
    """
    session_url = f"http://localhost:{hassette_port}/api/auth/session"
    body = json.dumps({"token": DEMO_AUTH_TOKEN}).encode("utf-8")
    req = urllib.request.Request(
        session_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_SOCKET_TIMEOUT_SECONDS) as resp:
            set_cookie = resp.headers.get("Set-Cookie")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError) as exc:
        print(
            f"ERROR: POST /api/auth/session failed ({exc}) -- DEMO_AUTH_TOKEN in "
            "capture_screenshots.py must match HASSETTE__WEB_API__AUTH_TOKEN in ha-demo.yml",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)

    if not set_cookie:
        print("ERROR: POST /api/auth/session returned no Set-Cookie header", file=sys.stderr, flush=True)
        sys.exit(1)

    cookie: http.cookies.SimpleCookie = http.cookies.SimpleCookie()
    cookie.load(set_cookie)
    if len(cookie) != 1:
        print(f"ERROR: expected exactly one cookie in Set-Cookie, got {len(cookie)}", file=sys.stderr, flush=True)
        sys.exit(1)
    ((name, morsel),) = cookie.items()
    max_age = int(morsel["max-age"]) if morsel["max-age"] else DEFAULT_SESSION_MAX_AGE_SECONDS

    return {
        "cookies": [
            {
                "name": name,
                "value": morsel.value,
                "domain": "localhost",
                "path": "/",
                "expires": time.time() + max_age,
                "httpOnly": True,
                "secure": False,
                "sameSite": "Strict",
            }
        ],
        "origins": [],
    }


def _needs_xvfb() -> bool:
    """Check if xvfb-run is needed (no working X display) and available."""
    if shutil.which("xvfb-run") is None:
        return False
    try:
        subprocess.run(
            ["xdpyinfo"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return False
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return True


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


def _run_shot_scraper(
    entries: list[dict[str, object]],
    repo_root: Path,
    timeout_ms: int,
    auth_path: str | None,
) -> int:
    """Run one shot-scraper ``multi`` invocation over `entries`, returning its exit code.

    `auth_path`, when given, is passed as shot-scraper's ``--auth`` flag (a Playwright
    storage-state JSON file) -- shot-scraper only accepts one ``--auth`` file per invocation
    (`shot_scraper.cli.multi`), so a manifest split between authenticated and unauthenticated
    pages needs one call per group rather than a per-entry override.
    """
    if not entries:
        return 0

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yml",
        delete=False,
        prefix="hassette-screenshots-",
    ) as tmp_manifest:
        yaml.dump(entries, tmp_manifest, default_flow_style=False, allow_unicode=True)
        tmp_manifest_path = tmp_manifest.name

    try:
        label = "authenticated" if auth_path else "unauthenticated"
        print(f"\nRunning shot-scraper ({len(entries)} {label} screenshots)...", flush=True)
        shot_cmd = ["uv", "run", "shot-scraper", "multi", tmp_manifest_path]
        if auth_path:
            shot_cmd.extend(["--auth", auth_path])
        if timeout_ms != 30000:
            shot_cmd.extend(["--timeout", str(timeout_ms)])
        if _needs_xvfb():
            shot_cmd = ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1920x1080x24", *shot_cmd]
        try:
            result = subprocess.run(
                shot_cmd,
                cwd=str(repo_root),
                timeout=SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            print(
                f"ERROR: shot-scraper did not finish within {SCREENSHOT_CAPTURE_TIMEOUT_SECONDS}s",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)
        return result.returncode
    finally:
        with contextlib.suppress(OSError):
            Path(tmp_manifest_path).unlink(missing_ok=True)


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
    parser.add_argument(
        "--timeout",
        type=int,
        default=30000,
        help="Playwright page timeout in milliseconds (default: 30000). "
        "Increase if Page.screenshot times out waiting for fonts or rendering.",
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

        resolved = _resolve_manifest(entries, str(demo.vite_port))

        if args.only:
            filters = [f.strip() for f in args.only.split(",")]
            resolved = [e for e in resolved if any(f in e.get("output", "") for f in filters)]
            if not resolved:
                print(f"ERROR: --only {args.only!r} matched no manifest entries", file=sys.stderr, flush=True)
                sys.exit(1)
            print(f"Filtered to {len(resolved)} entries matching --only {args.only!r}", flush=True)

        # The login view (`unauthenticated: true` in the manifest) must be captured with no
        # session cookie applied, or it redirects straight to the dashboard -- every other entry
        # needs the cookie. shot-scraper only accepts one `--auth` file per invocation, so the two
        # groups run as separate shot-scraper calls rather than a per-entry override.
        unauthenticated_entries = [e for e in resolved if e.get("unauthenticated")]
        authenticated_entries = [e for e in resolved if not e.get("unauthenticated")]

        auth_storage_state = _mint_auth_storage_state(demo.hassette_port)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            prefix="hassette-auth-",
        ) as tmp_auth:
            json.dump(auth_storage_state, tmp_auth)
            tmp_auth_path = tmp_auth.name

        try:
            return_code = _run_shot_scraper(authenticated_entries, repo_root, args.timeout, tmp_auth_path)
            return_code = _run_shot_scraper(unauthenticated_entries, repo_root, args.timeout, None) or return_code
        finally:
            with contextlib.suppress(OSError):
                Path(tmp_auth_path).unlink(missing_ok=True)

    sys.exit(return_code)


if __name__ == "__main__":
    main()
