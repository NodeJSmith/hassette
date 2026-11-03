#!/usr/bin/env python3
"""Capture doc screenshots from docs/screenshots.yml, or ad-hoc PR screenshots from a running hassette.

Usage:
    uv run python scripts/capture_screenshots.py
    uv run python scripts/capture_screenshots.py --against 18799 --token-file <data_dir>/.web_api_token \
        --url /apps/pet_feeder --url /apps --out /tmp/pr-shots

Requirements:
    - Docker must be running for docs mode (used by the demo stack for HA + hassette + Vite);
      --against mode doesn't need it
    - Playwright and Chromium must be installed:
          uv run playwright install --with-deps chromium
    - shot-scraper must be installed (dev dependency):
          uv sync --group dev

Docs-mode flow:
    1. Delete stale demo DB files
    2. Start the demo stack (HA + hassette + Vite) via DemoStack
    3. Poll until demo_stimulator has generated error data (up to 90 seconds)
    4. Resolve {port} and {ha_port} placeholders and inject animation-disabling
       CSS and the window.docShot page helpers
    5. Mint a session cookie for the demo auth token, add a Home Assistant login
       for HA_ACCESS_TOKEN, and save both as Playwright storage state
       (see _mint_auth_storage_state)
    6. Run shot-scraper twice: once with that storage state for every
       authenticated page, once with no auth for pages marked
       `unauthenticated: true` in the manifest (currently only /login)
    7. Tear down the demo stack

Output:
    All docs/_static/web_ui_*.png and docs/_static/ha-*.png files defined in
    docs/screenshots.yml.

Adding a new screenshot:
    Add an entry to docs/screenshots.yml with the URL path, output filename,
    and any selector/javascript needed to set up the UI state.  No changes to
    this script are needed.

--against mode (PR evidence for states the demo stack can't produce):
    Captures each --url from a hassette you already started (a seeded DB, a
    config naming only some of the seed's apps, ...) instead of the demo stack.
    It skips the demo stack, the manifest and the Home Assistant login, and
    writes <out>/<url-slug>.png. The token file is the instance's
    <data_dir>/.web_api_token. Recipe: .claude/rules/demo-and-screenshots.md.
"""

import argparse
import contextlib
import http.cookies
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

import yaml
from demo_stack import DemoStack
from dotenv import dotenv_values

ERROR_DATA_TIMEOUT_SECONDS = 90
ERROR_DATA_POLL_INTERVAL_SECONDS = 2
HTTP_SOCKET_TIMEOUT_SECONDS = 5
SCREENSHOT_CAPTURE_TIMEOUT_SECONDS = 600
DEFAULT_SESSION_MAX_AGE_SECONDS = 3600  # WebApiConfig.session_ttl's own default, used only if a
# Set-Cookie response is somehow missing Max-Age
HA_LOGIN_TTL_SECONDS = 86400
HA_FRONTEND_TOKENS_KEY = "hassTokens"
"""localStorage key where the Home Assistant frontend keeps its login."""

PAGE_HELPERS_JS = (Path(__file__).resolve().parent / "screenshot_page_helpers.js").read_text()

# Single source of truth: scripts/docker/.env, also read by ha-demo.yml (via docker-compose's
# auto env-file loading) and .mise/tasks/demo-verify (via grep).
DEMO_ENV_PATH = Path(__file__).resolve().parent / "docker" / ".env"

AGAINST_DEFAULT_WIDTH = 1400
AGAINST_DEFAULT_HEIGHT = 900
AGAINST_DEFAULT_WAIT_MS = 2000
URL_SLUG_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")

EXPECTED_COOKIE_COUNT = 1
"""Set-Cookie from POST /api/auth/session mints exactly one cookie (the session cookie)."""

ANIMATION_DISABLE_JS = (
    "const s=document.createElement('style');"
    "s.textContent='*,*::before,*::after{"
    "animation-duration:0s!important;"
    "transition-duration:0s!important;"
    "}';"
    "document.head.appendChild(s);"
)


def demo_env_value(key: str) -> str:
    """Read `key` from scripts/docker/.env, exiting if it's missing or empty."""
    value = dotenv_values(DEMO_ENV_PATH).get(key)
    if not value:
        print(f"ERROR: {key} not found in {DEMO_ENV_PATH}", file=sys.stderr, flush=True)
        sys.exit(1)
    return value


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


def _wait_for_error_data(hassette_port: int, auth_token: str) -> None:
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
            req = urllib.request.Request(jobs_url, headers={"Authorization": f"Bearer {auth_token}"})
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


def _ha_login_origin(ha_port: int, ha_access_token: str) -> dict[str, object]:
    """Build the storage-state origin that logs the Home Assistant frontend in with `ha_access_token`."""
    ha_url = f"http://localhost:{ha_port}"
    tokens = {
        "access_token": ha_access_token,
        "token_type": "Bearer",
        "expires_in": HA_LOGIN_TTL_SECONDS,
        "hassUrl": ha_url,
        "clientId": f"{ha_url}/",
        "expires": int((time.time() + HA_LOGIN_TTL_SECONDS) * 1000),
        "refresh_token": "",
    }
    return {"origin": ha_url, "localStorage": [{"name": HA_FRONTEND_TOKENS_KEY, "value": json.dumps(tokens)}]}


def _mint_auth_storage_state(
    hassette_port: int, auth_token: str, origins: Sequence[dict[str, object]] = ()
) -> dict[str, object]:
    """Build Playwright storage state holding a hassette session cookie minted from `auth_token`, plus `origins`.

    shot-scraper's ``--auth`` flag loads its argument file's JSON directly as Playwright's
    ``storage_state`` context argument (``shot_scraper.cli._browser_context``), so building that
    JSON here authenticates every subsequent page load with no browser-driven login.

    The cookie's domain is pinned to bare ``localhost`` rather than the Vite dev server's port —
    cookies are not port-scoped, and every doc screenshot is captured against
    ``http://localhost:{vite_port}``, which Vite proxies to hassette server-side (see
    ``VITE_PROXY_TARGET`` in ``scripts/docker/ha-demo.yml``) — so the browser only ever talks to
    one origin, ``localhost``, regardless of which port is behind it. Home Assistant ignores that
    cookie and reads its login from localStorage, which is keyed by port, so a caller that also
    captures HA pages passes ``_ha_login_origin`` in `origins`.
    """
    session_url = f"http://localhost:{hassette_port}/api/auth/session"
    body = json.dumps({"token": auth_token}).encode("utf-8")
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
            f"ERROR: POST {session_url} failed ({exc}) -- "
            "check that hassette is running and that the token comes from its data_dir",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)

    if not set_cookie:
        print("ERROR: POST /api/auth/session returned no Set-Cookie header", file=sys.stderr, flush=True)
        sys.exit(1)

    cookie: http.cookies.SimpleCookie = http.cookies.SimpleCookie()
    cookie.load(set_cookie)
    if len(cookie) != EXPECTED_COOKIE_COUNT:
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
        "origins": list(origins),
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


def _resolve_manifest(entries: Sequence[object], port: str, ha_port: str) -> list[dict[str, object]]:
    """Replace {port} and {ha_port} placeholders and prepend the animation-disabling JS and page helpers."""
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
        e["url"] = url.replace("{port}", port).replace("{ha_port}", ha_port)
        existing_js = e.get("javascript") or ""
        e["javascript"] = ANIMATION_DISABLE_JS + PAGE_HELPERS_JS + str(existing_js)
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


def url_slug(path: str) -> str:
    """Turn a URL path into a filename stem: ``/apps/pet_feeder`` -> ``apps-pet_feeder``, ``/`` -> ``index``."""
    return URL_SLUG_UNSAFE_RE.sub("-", path).strip("-") or "index"


def against_entries(
    urls: list[str], port: int, out_dir: Path, width: int, height: int, wait_ms: int
) -> list[dict[str, object]]:
    """Build shot-scraper entries for `--against` mode, one per URL path, written to ``<out_dir>/<slug>.png``.

    Raises:
        ValueError: A URL doesn't start with ``/``, or two URLs map to the same output file.
    """
    entries: list[dict[str, object]] = []
    outputs: dict[Path, str] = {}
    for url in urls:
        if not url.startswith("/"):
            raise ValueError(f"--url takes a path starting with '/', got {url!r}")
        output = out_dir / f"{url_slug(url)}.png"
        if output in outputs:
            raise ValueError(f"--url {url!r} and {outputs[output]!r} would both write {output.name}")
        outputs[output] = url
        # Entries go through the same resolver as docs/screenshots.yml's, which fills the {port}
        # placeholder and prepends the animation-disabling JS and page helpers.
        entries.append(
            {
                "url": f"http://localhost:{{port}}{url}",
                "output": str(output),
                "width": width,
                "height": height,
                "wait": wait_ms,
            }
        )
    return _resolve_manifest(entries, str(port), "")


def run_capture(
    authenticated: list[dict[str, object]],
    unauthenticated: list[dict[str, object]],
    storage_state: dict[str, object],
    repo_root: Path,
    timeout_ms: int,
) -> int:
    """Run shot-scraper over both entry groups, the first with `storage_state` as its auth, returning the exit code.

    The login view (`unauthenticated: true` in the manifest) must be captured with no session
    cookie applied, or it redirects straight to the dashboard -- every other entry needs the
    cookie. shot-scraper only accepts one `--auth` file per invocation, so the two groups run as
    separate shot-scraper calls rather than a per-entry override. An empty group is skipped.
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        prefix="hassette-auth-",
    ) as tmp_auth:
        json.dump(storage_state, tmp_auth)
        tmp_auth_path = tmp_auth.name

    try:
        return_code = _run_shot_scraper(authenticated, repo_root, timeout_ms, tmp_auth_path)
        return _run_shot_scraper(unauthenticated, repo_root, timeout_ms, None) or return_code
    finally:
        with contextlib.suppress(OSError):
            Path(tmp_auth_path).unlink(missing_ok=True)


def capture_docs(repo_root: Path, only: str | None, timeout_ms: int) -> int:
    """Capture docs/screenshots.yml's entries against a fresh demo stack."""
    auth_token = demo_env_value("DEMO_AUTH_TOKEN")
    ha_access_token = demo_env_value("HA_ACCESS_TOKEN")

    manifest_path = repo_root / "docs" / "screenshots.yml"
    with manifest_path.open() as f:
        entries = yaml.safe_load(f)

    if not isinstance(entries, list) or not entries:
        print(f"ERROR: {manifest_path} did not parse to a non-empty list", file=sys.stderr, flush=True)
        sys.exit(1)

    _clean_stale_demo_db(repo_root)

    print("Starting demo stack...", flush=True)
    with DemoStack() as demo:
        _wait_for_error_data(demo.hassette_port, auth_token)

        resolved = _resolve_manifest(entries, str(demo.vite_port), str(demo.ha_port))

        if only:
            filters = [f.strip() for f in only.split(",")]
            resolved = [e for e in resolved if any(f in str(e.get("output", "")) for f in filters)]
            if not resolved:
                print(f"ERROR: --only {only!r} matched no manifest entries", file=sys.stderr, flush=True)
                sys.exit(1)
            print(f"Filtered to {len(resolved)} entries matching --only {only!r}", flush=True)

        storage_state = _mint_auth_storage_state(
            demo.hassette_port, auth_token, [_ha_login_origin(demo.ha_port, ha_access_token)]
        )
        return run_capture(
            [e for e in resolved if not e.get("unauthenticated")],
            [e for e in resolved if e.get("unauthenticated")],
            storage_state,
            repo_root,
            timeout_ms,
        )


def capture_against(args: argparse.Namespace, repo_root: Path) -> int:
    """Capture `--url` paths from the already-running hassette on port `--against`."""
    # shot-scraper runs from repo_root, so a relative --out must be resolved against the caller's cwd first.
    out_dir = args.out.resolve()
    try:
        entries = against_entries(args.url, args.against, out_dir, args.width, args.height, args.wait)
        auth_token = args.token_file.read_text().strip()
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    storage_state = _mint_auth_storage_state(args.against, auth_token)
    return_code = run_capture(entries, [], storage_state, repo_root, args.timeout)
    if return_code == 0:
        for entry in entries:
            print(entry["output"], flush=True)
    return return_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
    against_group = parser.add_argument_group("--against mode", "capture ad-hoc URLs from an already-running hassette")
    against_group.add_argument("--against", type=int, metavar="PORT", help="web API port of the running hassette")
    against_group.add_argument(
        "--token-file", type=Path, help="the instance's web API token file: <data_dir>/.web_api_token"
    )
    against_group.add_argument(
        "--url", action="append", default=[], help="page path to capture, e.g. /apps/pet_feeder (repeatable)"
    )
    against_group.add_argument("--out", type=Path, help="output directory; keep it outside docs/")
    against_group.add_argument(
        "--width", type=int, default=AGAINST_DEFAULT_WIDTH, help="viewport width (default: %(default)s)"
    )
    against_group.add_argument(
        "--height", type=int, default=AGAINST_DEFAULT_HEIGHT, help="viewport height (default: %(default)s)"
    )
    against_group.add_argument(
        "--wait",
        type=int,
        default=AGAINST_DEFAULT_WAIT_MS,
        help="ms to wait before each capture (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    against_only = {"--token-file": args.token_file, "--url": args.url, "--out": args.out}
    if args.against is None:
        stray = [flag for flag, value in against_only.items() if value]
        if stray:
            parser.error(f"{', '.join(stray)}: valid only with --against")
    else:
        if args.only:
            parser.error("--only filters docs/screenshots.yml and doesn't apply with --against")
        missing = [flag for flag, value in against_only.items() if not value]
        if missing:
            parser.error(f"--against needs {', '.join(missing)}")
    return args


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    if args.against is not None:
        sys.exit(capture_against(args, repo_root))
    sys.exit(capture_docs(repo_root, args.only, args.timeout))


if __name__ == "__main__":
    main()
