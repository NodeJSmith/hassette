"""System tests for real OS-level SIGINT shutdown behavior.

Unlike the rest of the system suite, these tests spawn ``hassette run`` as a real subprocess
rather than driving ``Hassette`` in-process via ``startup_context`` — the whole point is to
send actual SIGINT signals to a real process and observe wall-clock exit timing, which an
in-process test cannot exercise (there is no separate OS process to signal).

Regression coverage for design/audits/2026-09-02-dx-onboarding-audit.md F1 (a single Ctrl+C
used to burn the full 30s shutdown timeout with zero output) and the follow-up fix that blocks
SIGINT process-wide and waits for it on a dedicated ``signal.sigwait()`` thread, so a second
Ctrl+C can force an exit even while a shutdown hook has the event loop thread genuinely blocked
(see ``server.py``).
"""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx2 as httpx
import pytest

from .conftest import HA_TOKEN, free_port

pytestmark = [pytest.mark.system_destructive]

READY_TIMEOUT = 60.0  # generous — cold subprocess import + real HA connection
GRACEFUL_EXIT_TIMEOUT = 10.0  # well under the 30s shutdown timeout the old bug used to burn
FORCE_EXIT_TIMEOUT = 10.0
STALL_MARKER = "STALL_STARTING"

STALLING_APP_SOURCE = f'''
"""Fixture app whose on_shutdown blocks the event loop thread synchronously.

Written to disk by test_sigint_shutdown.py and picked up via app autodetection — this
reproduces resources/operations.py's "await method()" directly awaiting a user-authored async
hook that performs blocking synchronous work, which is what the second-SIGINT force-exit path
must survive.
"""

import time

from hassette import App, AppConfig


class StallingShutdownApp(App[AppConfig]):
    async def on_shutdown(self) -> None:
        print({STALL_MARKER!r}, flush=True)
        time.sleep(120)
'''


def _spawn_hassette(tmp_path: Path, ha_url: str, *, apps_dir: Path | None = None) -> tuple[subprocess.Popen[str], str]:
    """Start a real ``hassette run`` subprocess and return it plus its web API base URL.

    Uses env vars (not a config file) so ``cwd=tmp_path`` never picks up a stray
    ``.env``/``hassette.toml`` from elsewhere on disk.
    """
    data_dir = tmp_path / "data"
    resolved_apps_dir = apps_dir or (tmp_path / "apps")
    resolved_apps_dir.mkdir(parents=True, exist_ok=True)
    port = free_port()

    env = {
        **os.environ,
        "HASSETTE__DATA_DIR": str(data_dir),
        "HASSETTE__APPS__DIRECTORY": str(resolved_apps_dir),
        "HASSETTE__APPS__AUTODETECT": "true" if apps_dir else "false",
        "HASSETTE__WEB_API__RUN": "true",
        "HASSETTE__WEB_API__PORT": str(port),
        "HASSETTE__WEB_API__HOST": "127.0.0.1",
        "HASSETTE__WEB_API__AUTH_ENABLED": "false",
        "HASSETTE__LIFECYCLE__STARTUP_TIMEOUT_SECONDS": "30",
    }

    proc = subprocess.Popen(
        [sys.executable, "-m", "hassette", "run", "--token", HA_TOKEN, "--ha-url", ha_url],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc, f"http://127.0.0.1:{port}"


def _drain_stdout(proc: subprocess.Popen[str], marker: str, marker_seen: threading.Event) -> None:
    """Continuously read the subprocess's stdout so it never blocks on a full pipe buffer.

    Sets ``marker_seen`` the first time a line containing ``marker`` appears. Runs until the
    subprocess closes stdout (i.e. exits) so later output (shutdown logs, the force-exit
    warning) never backs up behind an unread pipe.
    """
    assert proc.stdout is not None
    for line in proc.stdout:
        if marker in line:
            marker_seen.set()


def _wait_ready(base_url: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/health/ready", timeout=2.0)
            if r.status_code == 200:
                return
        except Exception as exc:
            last_exc = exc
        time.sleep(0.5)
    raise TimeoutError(f"hassette at {base_url} did not become ready within {timeout}s: {last_exc}")


def _cleanup(proc: subprocess.Popen[str], reader: threading.Thread) -> None:
    """Ensure the subprocess, its stdout-draining thread, and the pipe itself are all closed.

    The reader thread's ``for line in proc.stdout`` loop only ends at EOF (the subprocess
    closing its end), so it's joined before the pipe is closed here — otherwise the suite's
    fatal ResourceWarning-as-error setting (see pyproject.toml) turns an unclosed pipe into a
    test failure.
    """
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=10)
    reader.join(timeout=5)
    if proc.stdout is not None:
        proc.stdout.close()


def test_sigint_exits_promptly_on_healthy_instance(ha_container: str, tmp_path: Path) -> None:
    """A single Ctrl+C on a healthy, idle instance exits in a few seconds, not a 30s hang.

    Regression test for audit finding F1: SIGINT used to fall through to asyncio's default
    disorderly-cancellation path and burn the full ``total_shutdown_timeout_seconds`` (30s)
    with zero hassette output before exiting.
    """
    proc, base_url = _spawn_hassette(tmp_path, ha_container)
    marker_seen = threading.Event()
    reader = threading.Thread(target=_drain_stdout, args=(proc, STALL_MARKER, marker_seen), daemon=True)
    reader.start()
    try:
        _wait_ready(base_url, timeout=READY_TIMEOUT)

        start = time.monotonic()
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=GRACEFUL_EXIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            pytest.fail(f"hassette did not exit within {GRACEFUL_EXIT_TIMEOUT}s of a single SIGINT")
        elapsed = time.monotonic() - start

        assert elapsed < GRACEFUL_EXIT_TIMEOUT, (
            f"SIGINT shutdown took {elapsed:.1f}s — expected a graceful exit well under {GRACEFUL_EXIT_TIMEOUT}s"
        )
        assert proc.returncode == 0, f"expected a clean exit, got returncode={proc.returncode}"
    finally:
        _cleanup(proc, reader)


def test_second_sigint_forces_exit_during_stalled_shutdown(ha_container: str, tmp_path: Path) -> None:
    """A second Ctrl+C forces an immediate exit even while a shutdown hook has the loop blocked.

    Reproduces the scenario a user-authored async shutdown hook creates
    (StallingShutdownApp.on_shutdown blocks the event loop thread synchronously). The second
    SIGINT is sent only once that hook has confirmed (via STALL_MARKER) that it is actually
    inside the blocking call — proving the dedicated sigwait() thread still receives and
    handles the signal while loop.add_signal_handler()'s callback could not have.
    """
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir(parents=True, exist_ok=True)
    (apps_dir / "stalling_shutdown_app.py").write_text(STALLING_APP_SOURCE)

    proc, base_url = _spawn_hassette(tmp_path, ha_container, apps_dir=apps_dir)
    marker_seen = threading.Event()
    reader = threading.Thread(target=_drain_stdout, args=(proc, STALL_MARKER, marker_seen), daemon=True)
    reader.start()
    try:
        _wait_ready(base_url, timeout=READY_TIMEOUT)

        # First SIGINT: requests graceful shutdown, which reaches StallingShutdownApp's
        # on_shutdown and blocks there.
        proc.send_signal(signal.SIGINT)
        if not marker_seen.wait(timeout=READY_TIMEOUT):
            pytest.fail(f"StallingShutdownApp.on_shutdown never started stalling within {READY_TIMEOUT}s")

        # Second SIGINT: shutdown_event is already set and the loop thread is confirmed stuck
        # inside the blocking sleep — this is exactly the case loop.add_signal_handler() could
        # not reach.
        start = time.monotonic()
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=FORCE_EXIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            pytest.fail(f"second SIGINT did not force-exit within {FORCE_EXIT_TIMEOUT}s")
        elapsed = time.monotonic() - start

        assert elapsed < FORCE_EXIT_TIMEOUT, (
            f"force-exit took {elapsed:.1f}s — expected os._exit well under {FORCE_EXIT_TIMEOUT}s"
        )
        assert proc.returncode == 1, f"expected the os._exit(1) force-exit code, got returncode={proc.returncode}"
    finally:
        _cleanup(proc, reader)
