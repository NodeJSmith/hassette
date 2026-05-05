#!/usr/bin/env python3
"""Demo orchestrator: starts HA + hassette + Vite for visual QA.

Usage:
    uv run python scripts/hassette_demo.py

Allocates three free ports dynamically, starts all services in sequence,
prints machine-parseable KEY=value lines when ready, and blocks until
signaled.  On SIGINT or SIGTERM all services are torn down in reverse order.

All paths are derived from this script's own location — no hardcoded
absolute paths.  The script uses only stdlib modules so it works before
``uv sync`` has been run.
"""

import atexit
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Must match the pre-seeded JWT in tests/fixtures/demo-ha-config/.storage/auth
# and the healthcheck in scripts/docker/ha-demo.yml
HA_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiIwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMyIsImlhdCI6MTczNT"
    "Y4OTYwMCwiZXhwIjoyMDUxMDQ5NjAwfQ"
    ".q-p85dOe-MMnKQhSNh_LEWnWJGK-GA3xdmqb4LKvkU0"
)

# ---------------------------------------------------------------------------
# State tracked across startup so teardown knows what to clean up
# ---------------------------------------------------------------------------

_ha_compose_file: Path | None = None
_ha_env: dict[str, str] | None = None
_hassette_proc: "subprocess.Popen[bytes] | None" = None
_vite_proc: "subprocess.Popen[bytes] | None" = None
_tmp_dir: str | None = None
_torn_down = False


# ---------------------------------------------------------------------------
# Port allocation
# ---------------------------------------------------------------------------


def find_free_port() -> int:
    """Return a free TCP port on localhost.

    Binds to port 0 (OS assigns a free port), reads the assigned port,
    then closes the socket.  There is a small TOCTOU window between the
    close and the service binding, but it is acceptable for this use case.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------------------
# Readiness polling
# ---------------------------------------------------------------------------


def _poll_http(
    url: str,
    *,
    timeout_seconds: int,
    poll_interval: float = 2.0,
    headers: dict[str, str] | None = None,
    consecutive_required: int = 1,
) -> bool:
    """Poll *url* until it returns HTTP 200 or *timeout_seconds* elapses.

    Args:
        url: URL to GET.
        timeout_seconds: Maximum seconds to wait.
        poll_interval: Seconds between attempts.
        headers: Optional HTTP headers to include.
        consecutive_required: Number of consecutive 200 responses required.

    Returns:
        True if the required number of consecutive 200 responses was observed
        before the timeout, False otherwise.
    """
    deadline = time.monotonic() + timeout_seconds
    consecutive = 0
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    consecutive += 1
                    if consecutive >= consecutive_required:
                        return True
                else:
                    consecutive = 0
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                print(f"DEMO_ERROR=HTTP {exc.code} from {url} (check credentials)", flush=True)
                return False
            if exc.code not in (503, 404):
                print(f"DEMO_WARN=HTTP {exc.code} from {url}", flush=True)
            consecutive = 0
        except Exception:
            consecutive = 0
        time.sleep(poll_interval)
    return False


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


def teardown() -> None:
    """Terminate all services in reverse startup order.

    Idempotent — safe to call from both signal handlers and atexit.
    """
    global _torn_down
    if _torn_down:
        return
    _torn_down = True

    # 1. Terminate Vite process group
    if _vite_proc is not None:
        try:
            os.killpg(_vite_proc.pid, signal.SIGTERM)
            _vite_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                os.killpg(_vite_proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

    # 2. Terminate hassette process group
    if _hassette_proc is not None:
        try:
            os.killpg(_hassette_proc.pid, signal.SIGTERM)
            _hassette_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                os.killpg(_hassette_proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

    # 3. docker compose down
    if _ha_compose_file is not None and _ha_env is not None:
        with contextlib.suppress(Exception):
            subprocess.run(
                ["docker", "compose", "-f", str(_ha_compose_file), "down"],
                check=False,
                env=_ha_env,
            )

    # 4. Remove temp directory
    if _tmp_dir is not None:
        shutil.rmtree(_tmp_dir, ignore_errors=True)


def _signal_handler(_signum: int, _frame: object) -> None:
    teardown()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    global _ha_compose_file, _ha_env, _hassette_proc, _vite_proc, _tmp_dir

    # Register cleanup handlers early so partial startup is also cleaned up.
    atexit.register(teardown)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # ------------------------------------------------------------------
    # Step 1: Resolve repo root
    # ------------------------------------------------------------------
    repo_root = Path(__file__).resolve().parent.parent

    if sys.platform == "win32":
        print("DEMO_ERROR=This script requires Unix (Linux/macOS)", flush=True)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2: Allocate three free ports
    # ------------------------------------------------------------------
    ha_port = find_free_port()
    hassette_port = find_free_port()
    vite_port = find_free_port()

    # ------------------------------------------------------------------
    # Step 3: Copy demo HA fixture to temp directory
    # ------------------------------------------------------------------
    fixture_src = repo_root / "tests" / "fixtures" / "demo-ha-config"
    # Keep in sync with tests/system/conftest.py ha_container fixture (same ignore list)
    _ignore = shutil.ignore_patterns(
        ".HA_VERSION",
        "home-assistant.log*",
        "known_devices.yaml",
        "blueprints",
        "core.area_registry",
        "core.device_registry",
        "core.entity_registry",
        "core.restore_state",
        "homeassistant.exposed_entities",
        "http",
        "http.auth",
        "person",
        "repairs.issue_registry",
        "trace.saved_traces",
    )
    _tmp_dir = tempfile.mkdtemp(prefix="hassette-demo-")
    shutil.copytree(str(fixture_src), _tmp_dir, dirs_exist_ok=True, ignore=_ignore)

    # ------------------------------------------------------------------
    # Step 4: Start HA container
    # ------------------------------------------------------------------
    compose_file = repo_root / "scripts" / "docker" / "ha-demo.yml"
    _ha_compose_file = compose_file

    # Check Docker availability first
    docker_check = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        cwd=str(repo_root),
    )
    if docker_check.returncode != 0:
        print("DEMO_ERROR=Docker is not running or not installed", flush=True)
        sys.exit(1)

    ha_env = {
        **os.environ,
        "HA_PORT": str(ha_port),
        "HA_CONFIG_PATH": _tmp_dir,
    }
    _ha_env = ha_env

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        check=False,
        capture_output=True,
        env=ha_env,
        cwd=str(repo_root),
    )
    if result.returncode != 0:
        print(f"DEMO_ERROR=docker compose up failed: {result.stderr.decode().strip()}", flush=True)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 5: Poll HA readiness
    # Unlike tests/system/conftest.py wait_for_ha_ready(), this skips the
    # WebSocket probe to stay stdlib-only. The 3-consecutive-200s check is
    # a reasonable approximation for the demo use case.
    # ------------------------------------------------------------------
    ha_ready = _poll_http(
        f"http://localhost:{ha_port}/api/",
        timeout_seconds=60,
        poll_interval=2.0,
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
        consecutive_required=3,
    )
    if not ha_ready:
        print("DEMO_ERROR=HA failed to start within 60s", flush=True)
        teardown()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 6: Start hassette subprocess
    # ------------------------------------------------------------------
    hassette_env = {
        **os.environ,
        "HASSETTE__BASE_URL": f"http://localhost:{ha_port}",
        "HASSETTE__TOKEN": HA_TOKEN,
        "HASSETTE__WEB_API_PORT": str(hassette_port),
        "HASSETTE__APP_DIR": str(repo_root / "examples"),
        "HASSETTE__DATA_DIR": str(repo_root / ".demo-data"),
    }
    _hassette_proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "hassette", "--config-file", str(repo_root / "examples" / "hassette.toml")],
        env=hassette_env,
        cwd=str(repo_root),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # ------------------------------------------------------------------
    # Step 7: Poll hassette readiness
    # ------------------------------------------------------------------
    hassette_ready = _poll_http(
        f"http://localhost:{hassette_port}/api/health",
        timeout_seconds=30,
        poll_interval=2.0,
    )
    if not hassette_ready:
        print("DEMO_ERROR=Hassette failed to start within 30s", flush=True)
        teardown()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 8: Check node_modules
    # ------------------------------------------------------------------
    node_modules_dir = repo_root / "frontend" / "node_modules"
    if not node_modules_dir.exists():
        npm_result = subprocess.run(
            ["npm", "ci", "--prefix", str(repo_root / "frontend")],
            check=False,
            capture_output=True,
            cwd=str(repo_root),
        )
        if npm_result.returncode != 0:
            print(f"DEMO_ERROR=npm ci failed: {npm_result.stderr.decode().strip()}", flush=True)
            teardown()
            sys.exit(1)

    # ------------------------------------------------------------------
    # Step 9: Start Vite dev server
    # ------------------------------------------------------------------
    vite_env = {
        **os.environ,
        "VITE_PROXY_TARGET": f"http://localhost:{hassette_port}",
    }
    _vite_proc = subprocess.Popen(
        ["npm", "run", "dev", "--prefix", str(repo_root / "frontend"), "--", "--port", str(vite_port)],
        env=vite_env,
        cwd=str(repo_root),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Poll Vite readiness
    vite_ready = _poll_http(
        f"http://localhost:{vite_port}",
        timeout_seconds=15,
        poll_interval=2.0,
    )
    if not vite_ready:
        print("DEMO_ERROR=Vite failed to start within 15s", flush=True)
        teardown()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 10: Print structured ready message and block
    # ------------------------------------------------------------------
    print(f"DEMO_HA_URL=http://localhost:{ha_port}", flush=True)
    print(f"DEMO_HASSETTE_URL=http://localhost:{hassette_port}", flush=True)
    print(f"DEMO_FRONTEND_URL=http://localhost:{vite_port}", flush=True)
    print("DEMO_READY=true", flush=True)
    sys.stdout.flush()

    # Block until signaled — signal.pause() is Unix-only; Windows is rejected at startup.
    signal.pause()


if __name__ == "__main__":
    main()
