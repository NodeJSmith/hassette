"""Smoke system test for the demo environment.

Starts the demo orchestrator as a subprocess, waits for DEMO_READY=true,
queries the hassette API to confirm all 7 app instances are running, and
verifies the bus has registered listeners (confirming framework wiring).

Requires: Docker, uv, npm/node_modules.  Run via:
    uv run nox -s system
"""

import contextlib
import json
import os
import selectors
import signal
import subprocess
import time
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.system]

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ORCHESTRATOR = _REPO_ROOT / "scripts" / "hassette_demo.py"

_EXPECTED_INSTANCES = {
    "backyard_kitchen",
    "backyard_ceiling",
    "climate_controller",
    "cover_scheduler",
    "paulus",
    "home_boy",
    "security_monitor",
}


def _read_demo_output(proc: "subprocess.Popen[bytes]", timeout_seconds: int) -> dict[str, str]:
    """Read stdout lines from the demo process until DEMO_READY=true or timeout.

    Uses selectors to enforce a per-read wall-clock bound so readline()
    cannot block past the deadline.
    """
    parsed: dict[str, str] = {}
    deadline = time.monotonic() + timeout_seconds

    assert proc.stdout is not None

    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            ready = sel.select(timeout=max(0.0, remaining))
            if not ready:
                break

            line_bytes = proc.stdout.readline()
            if not line_bytes:
                rc = proc.poll()
                raise RuntimeError(f"Demo orchestrator exited (rc={rc}) before emitting DEMO_READY=true")

            line = line_bytes.decode(errors="replace").rstrip()
            if "=" in line:
                key, _, value = line.partition("=")
                parsed[key.strip()] = value.strip()

            if parsed.get("DEMO_READY") == "true":
                return parsed
    finally:
        sel.close()

    raise TimeoutError(f"DEMO_READY=true not received within {timeout_seconds}s")


def _poll_apps(
    hassette_url: str,
    *,
    expected_count: int,
    timeout_seconds: int,
    poll_interval: float = 1.0,
) -> list[dict[str, object]]:
    """Poll GET /api/apps until all expected_count apps are running."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{hassette_url}/api/apps", timeout=3)
            resp.raise_for_status()
            data = resp.json()
            apps = data.get("apps", [])
            running = [a for a in apps if a.get("status") == "running"]
            if len(running) >= expected_count:
                return apps  # pyright: ignore[reportReturnType]
        except (httpx.HTTPError, OSError, json.JSONDecodeError):
            pass
        time.sleep(poll_interval)

    raise TimeoutError(f"Not all {expected_count} apps reached running within {timeout_seconds}s")


def _get_listeners(hassette_url: str, *, retries: int = 3) -> list[dict[str, object]]:
    """GET /api/bus/listeners with retry for transient startup timing."""
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            resp = httpx.get(f"{hassette_url}/api/bus/listeners", timeout=5)
            resp.raise_for_status()
            return resp.json()  # pyright: ignore[reportReturnType]
        except (httpx.HTTPError, OSError) as exc:
            last_exc = exc
            time.sleep(1.0)
    raise RuntimeError(f"GET /api/bus/listeners failed after {retries} attempts") from last_exc


def test_all_apps_running() -> None:
    """Start demo env, verify all 7 app instances reach running, then tear down."""
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            ["uv", "run", "python", str(_ORCHESTRATOR)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(_REPO_ROOT),
            start_new_session=True,
        )

        demo_vars = _read_demo_output(proc, timeout_seconds=120)

        hassette_url = demo_vars.get("DEMO_HASSETTE_URL", "")
        assert hassette_url, f"DEMO_HASSETTE_URL not found in orchestrator output: {demo_vars}"

        apps = _poll_apps(
            hassette_url,
            expected_count=len(_EXPECTED_INSTANCES),
            timeout_seconds=30,
        )

        instance_names = {a.get("instance_name") for a in apps}
        running_names = {a.get("instance_name") for a in apps if a.get("status") == "running"}

        assert len(apps) == len(_EXPECTED_INSTANCES), (
            f"Expected {len(_EXPECTED_INSTANCES)} app instances, got {len(apps)}: {instance_names}"
        )
        assert running_names == _EXPECTED_INSTANCES, (
            f"Not all instances are running.\n"
            f"  Expected: {_EXPECTED_INSTANCES}\n"
            f"  Running:  {running_names}\n"
            f"  All apps: {[(a.get('instance_name'), a.get('status')) for a in apps]}"
        )

        listeners = _get_listeners(hassette_url)
        assert len(listeners) > 0, (
            "No listeners found via GET /api/bus/listeners — framework wiring may have failed. "
            "Apps are running but no event subscriptions were registered."
        )

    finally:
        if proc is not None:
            # start_new_session=True makes the child a process group leader (pgid == pid)
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError, OSError):
                    os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
