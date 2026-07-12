"""Shared demo stack lifecycle: fixture copy, compose up/down, signal handling.

``DemoStack`` is a context manager that starts the HA + hassette + Vite
compose stack and guarantees teardown on exit, signal, or interpreter
shutdown. Both ``hassette_demo.py`` and ``capture_screenshots.py`` import it
to avoid duplicating subprocess lifecycle management.

Example:
    with DemoStack() as demo:
        print(f"Frontend: http://localhost:{demo.vite_port}")
        signal.pause()
    # docker compose down runs automatically here
"""

import atexit
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from types import FrameType, TracebackType

COMPOSE_PROJECT_NAME = "hassette-demo"
COMPOSE_UP_TIMEOUT_SECONDS = 120
COMPOSE_DOWN_TIMEOUT_SECONDS = 30

DEFAULT_HA_PORT = 18123
DEFAULT_HASSETTE_PORT = 18126
DEFAULT_VITE_PORT = 15173


class DemoStack:
    """Context manager for the compose-native demo stack.

    Copies the HA fixture config to a temp directory, runs
    ``docker compose up -d --wait``, and tears down (compose down +
    tmpdir cleanup) on ``__exit__``, SIGINT/SIGTERM, or atexit.
    """

    def __init__(self) -> None:
        self._repo_root = Path(__file__).resolve().parent.parent
        self._compose_file = self._repo_root / "scripts" / "docker" / "ha-demo.yml"
        self._ha_port = int(os.environ.get("DEMO_HA_PORT", DEFAULT_HA_PORT))
        self._hassette_port = int(os.environ.get("DEMO_HASSETTE_PORT", DEFAULT_HASSETTE_PORT))
        self._vite_port = int(os.environ.get("DEMO_VITE_PORT", DEFAULT_VITE_PORT))
        self._tmp_dir: str | None = None
        self._torn_down = False

    @property
    def ha_port(self) -> int:
        return self._ha_port

    @property
    def hassette_port(self) -> int:
        return self._hassette_port

    @property
    def vite_port(self) -> int:
        return self._vite_port

    def __enter__(self) -> "DemoStack":
        docker_check = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            cwd=str(self._repo_root),
        )
        if docker_check.returncode != 0:
            detail = docker_check.stderr.decode().strip() if docker_check.stderr else "unknown"
            raise RuntimeError(f"Docker is not running or not installed: {detail}")

        fixture_src = self._repo_root / "tests" / "fixtures" / "demo-ha-config"
        # Keep in sync with tests/system/conftest.py ha_container fixture (same ignore list)
        ignore = shutil.ignore_patterns(
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
        self._tmp_dir = tempfile.mkdtemp(prefix="hassette-demo-")
        atexit.register(self._teardown)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            shutil.copytree(str(fixture_src), self._tmp_dir, dirs_exist_ok=True, ignore=ignore)
        except Exception:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None
            raise

        env = {
            **os.environ,
            "HA_CONFIG_PATH": self._tmp_dir,
            "DEMO_HA_PORT": str(self._ha_port),
            "DEMO_HASSETTE_PORT": str(self._hassette_port),
            "DEMO_VITE_PORT": str(self._vite_port),
        }

        try:
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(self._compose_file),
                    "-p",
                    COMPOSE_PROJECT_NAME,
                    "up",
                    "-d",
                    "--wait",
                ],
                check=False,
                env=env,
                cwd=str(self._repo_root),
                timeout=COMPOSE_UP_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            self._teardown()
            raise RuntimeError(
                f"docker compose up did not become healthy within {COMPOSE_UP_TIMEOUT_SECONDS}s"
            ) from None
        if result.returncode != 0:
            self._teardown()
            raise RuntimeError(f"docker compose up failed (exit code {result.returncode})")

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._teardown()

    def _teardown(self) -> None:
        """Tear down compose services and the fixture tmpdir. Idempotent."""
        if self._torn_down:
            return
        self._torn_down = True

        with contextlib.suppress(Exception):
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(self._compose_file),
                    "-p",
                    COMPOSE_PROJECT_NAME,
                    "down",
                    "--remove-orphans",
                ],
                check=False,
                cwd=str(self._repo_root),
                timeout=COMPOSE_DOWN_TIMEOUT_SECONDS,
            )

        if self._tmp_dir is not None:
            # HA creates root-owned dirs (e.g. blueprints/) inside the bind-mounted
            # config path. shutil.rmtree can't delete those as a non-root user.
            # Clear root-owned contents via a throwaway container first.
            with contextlib.suppress(Exception):
                subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "-v",
                        f"{self._tmp_dir}:/d",
                        "python:3.14-slim",
                        "sh",
                        "-c",
                        "rm -rf /d/*",
                    ],
                    check=False,
                    capture_output=True,
                    timeout=10,
                )
            shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _signal_handler(self, _signum: int, _frame: FrameType | None) -> None:
        self._teardown()
        sys.exit(0)
