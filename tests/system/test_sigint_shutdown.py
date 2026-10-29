"""System tests for real OS-level SIGINT/SIGTERM shutdown behavior.

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

import signal
import subprocess
import threading
import time
from pathlib import Path

import httpx2 as httpx
import pytest

from tests.support.helpers import EXIT_TASK_SURVIVOR_ERROR, EXIT_WATCHDOG_ERROR, write_app

from .conftest import app_entries, free_port, hassette_run_env, spawn_hassette_run

pytestmark = [pytest.mark.system_destructive]

READY_TIMEOUT = 60.0  # generous — cold subprocess import + real HA connection
GRACEFUL_EXIT_TIMEOUT = 10.0  # well under the 30s shutdown timeout the old bug used to burn
FORCE_EXIT_TIMEOUT = 10.0
STALL_MARKER = "STALL_STARTING"

STALLING_APP_SOURCE = f'''
"""Fixture app whose on_shutdown blocks the event loop thread synchronously.

Written to disk and configured through env vars by test_sigint_shutdown.py — this
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


def _spawn_hassette(tmp_path: Path, ha_url: str) -> tuple[subprocess.Popen[str], str]:
    """Start a real ``hassette run`` subprocess on ``tmp_path / "apps"`` and return it plus its web API base URL.

    Uses env vars (not a config file) so ``cwd=tmp_path`` never picks up a stray
    ``.env``/``hassette.toml`` from elsewhere on disk. Every app class already written to the apps
    directory gets an entry, passed as nested ``HASSETTE__APPS__<KEY>__<FIELD>`` vars (``config`` keys one
    level deeper, as ``__CONFIG__<KEY>``): a JSON value on ``HASSETTE__APPS__<KEY>`` is not read as an app entry.
    """
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir(parents=True, exist_ok=True)
    port = free_port()

    app_vars: dict[str, str] = {}
    for key, entry in app_entries(apps_dir).items():
        prefix = f"HASSETTE__APPS__{key.upper()}__"
        for field, value in entry.items():
            if isinstance(value, dict):
                app_vars.update({f"{prefix}{field.upper()}__{k.upper()}": str(v) for k, v in value.items()})
            else:
                app_vars[f"{prefix}{field.upper()}"] = str(value)

    env = hassette_run_env(
        tmp_path / "data",
        port,
        HASSETTE__APPS__DIRECTORY=str(apps_dir),
        HASSETTE__LIFECYCLE__STARTUP_TIMEOUT_SECONDS="30",
        **app_vars,
    )
    proc = spawn_hassette_run(tmp_path, env, ha_url, subprocess.PIPE)
    return proc, f"http://127.0.0.1:{port}"


def _drain_stdout(
    proc: subprocess.Popen[str], marker: str, marker_seen: threading.Event, lines: list[str] | None = None
) -> None:
    """Continuously read the subprocess's stdout so it never blocks on a full pipe buffer.

    Sets ``marker_seen`` the first time a line containing ``marker`` appears, and appends every line to
    ``lines`` when given. Runs until the subprocess closes stdout (i.e. exits) so later output (shutdown
    logs, the force-exit warning) never backs up behind an unread pipe.
    """
    assert proc.stdout is not None
    for line in proc.stdout:
        if lines is not None:
            lines.append(line)
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


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM], ids=["sigint", "sigterm"])
def test_single_signal_exits_promptly_on_healthy_instance(
    ha_container: str, tmp_path: Path, sig: signal.Signals
) -> None:
    """A single Ctrl+C or ``docker stop`` on a healthy, idle instance exits 0 in a few seconds, without a hard exit.

    The readiness polls go through ``RuntimeDep``, a sync dependency FastAPI resolves on an AnyIO worker
    thread, so AnyIO workers exist at exit. A clean exit must not reach either of the exit check's hard
    exits (spec 141 D3): those would log an ERROR and exit ``EX_SOFTWARE``.

    Regression test for audit finding F1: SIGINT used to fall through to asyncio's default
    disorderly-cancellation path and burn the full ``total_shutdown_timeout_seconds`` with zero
    hassette output before exiting. SIGTERM pins that uvicorn's own SIGTERM handler, installed
    while it serves, doesn't keep hassette's from requesting shutdown first: otherwise the web API
    service's return reads as an unrequested stop of a required service and the process exits 1.
    """
    proc, base_url = _spawn_hassette(tmp_path, ha_container)
    marker_seen = threading.Event()
    lines: list[str] = []
    reader = threading.Thread(target=_drain_stdout, args=(proc, STALL_MARKER, marker_seen, lines), daemon=True)
    reader.start()
    try:
        _wait_ready(base_url, timeout=READY_TIMEOUT)

        start = time.monotonic()
        proc.send_signal(sig)
        try:
            proc.wait(timeout=GRACEFUL_EXIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            pytest.fail(f"hassette did not exit within {GRACEFUL_EXIT_TIMEOUT}s of a single {sig.name}")
        elapsed = time.monotonic() - start

        assert elapsed < GRACEFUL_EXIT_TIMEOUT, (
            f"{sig.name} shutdown took {elapsed:.1f}s — expected a graceful exit well under {GRACEFUL_EXIT_TIMEOUT}s"
        )
        assert proc.returncode == 0, f"expected a clean exit, got returncode={proc.returncode}"
        reader.join(timeout=5)
        assert not reader.is_alive(), "stdout was still open 5s after the process exited"
        hard_exit_lines = [line for line in lines if EXIT_TASK_SURVIVOR_ERROR in line or EXIT_WATCHDOG_ERROR in line]
        assert not hard_exit_lines, f"a clean exit reached the exit check's hard exit: {hard_exit_lines}"
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
    write_app(tmp_path / "apps", "stalling_shutdown_app.py", STALLING_APP_SOURCE)

    proc, base_url = _spawn_hassette(tmp_path, ha_container)
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
