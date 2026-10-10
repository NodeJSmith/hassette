"""System tests: a real ``hassette run`` finds and starts apps in the two common project layouts.

Each test builds a project on disk, launches ``hassette run`` as a subprocess from the project
root with no path settings in the environment, and checks through the web API that the app is
running. Config discovery, file-relative path anchoring and app import all run as they do for a
user, which the in-process system tests (they pass paths directly) don't exercise.

- Flat: ``hassette.toml`` and ``apps/`` side by side in the working directory.
- Project (``src`` layout): ``pyproject.toml`` at the root, apps in ``src/<pkg>``, config in
  ``config/hassette.toml`` pointing at ``../src/<pkg>``. The app imports a sibling module from its
  own package.
"""

import signal
import subprocess
import textwrap
import time
from pathlib import Path
from typing import Any, NamedTuple

import httpx2 as httpx
import pytest

from .conftest import free_port, hassette_run_env, spawn_hassette_run

pytestmark = [pytest.mark.system]

APP_RUNNING_TIMEOUT = 90.0  # cold subprocess import, HA connection, then app startup
EXIT_TIMEOUT = 30.0  # Hassette's own total shutdown timeout

GREETER_APP = textwrap.dedent(
    """
    from hassette import App


    class Greeter(App):
        async def on_initialize(self) -> None:
            self.logger.info("greeter started")
    """
)

PACKAGE_GREETER_APP = textwrap.dedent(
    """
    from hassette import App

    from mypkg.helpers import GREETING


    class Greeter(App):
        async def on_initialize(self) -> None:
            self.logger.info(GREETING)
    """
)


class HassetteRun(NamedTuple):
    proc: subprocess.Popen[str]
    base_url: str
    log_path: Path


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def start_hassette(project: Path, ha_url: str) -> HassetteRun:
    """Start ``hassette run`` from `project`, logging to a file beside it.

    Only the token, HA URL, web API and data dir come from outside the project. Pointing
    ``XDG_CONFIG_HOME`` into the test's tree keeps the platform config dir, which the default
    search reads first, from picking up a developer's own ``hassette.toml``.
    """
    port = free_port()
    env = hassette_run_env(project.parent / "data", port, XDG_CONFIG_HOME=str(project.parent / "xdg-config"))
    log_path = project.parent / "hassette.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = spawn_hassette_run(project, env, ha_url, log)
    return HassetteRun(proc, f"http://127.0.0.1:{port}", log_path)


def wait_for_running_app(run: HassetteRun, class_name: str) -> dict[str, Any]:
    """Poll ``/api/apps`` until an app of `class_name` reports ``running``, and return its summary."""
    deadline = time.monotonic() + APP_RUNNING_TIMEOUT
    apps: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        assert run.proc.poll() is None, f"hassette exited with {run.proc.returncode}:\n{run.log_path.read_text()}"
        try:
            resp = httpx.get(f"{run.base_url}/api/apps", timeout=2.0)
        except httpx.HTTPError:
            resp = None
        if resp is not None and resp.status_code == 200:
            apps = resp.json()["apps"]
            matches = [app for app in apps if app["class_name"] == class_name]
            if matches and matches[0]["status"] == "running":
                return matches[0]
        time.sleep(0.5)
    raise AssertionError(f"no running {class_name} app; last /api/apps: {apps}\n{run.log_path.read_text()}")


def stop(run: HassetteRun) -> int | None:
    """Stop the run with Ctrl+C and return its exit code, or None if it had to be killed."""
    if run.proc.poll() is not None:
        return run.proc.returncode
    run.proc.send_signal(signal.SIGINT)
    try:
        return run.proc.wait(timeout=EXIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        run.proc.kill()
        run.proc.wait(timeout=EXIT_TIMEOUT)
        return None


def test_flat_layout_starts_the_app(ha_container: str, tmp_path: Path) -> None:
    """``hassette.toml`` and ``apps/`` in the working directory: the app is autodetected and runs."""
    project = tmp_path / "home-automations"
    # an empty [hassette] table: the file only has to exist for discovery; apps default to ./apps
    write_file(project / "hassette.toml", "[hassette]\n")
    write_file(project / "apps" / "greeter.py", GREETER_APP)

    run = start_hassette(project, ha_container)
    try:
        app = wait_for_running_app(run, "Greeter")
    finally:
        exit_code = stop(run)

    assert app["filename"] == "greeter.py"
    assert exit_code == 0, run.log_path.read_text()
    # core.py logs "Apps directory: <path>" at startup
    assert f"Apps directory: {project / 'apps'}" in run.log_path.read_text()


def test_src_layout_project_starts_the_app(ha_container: str, tmp_path: Path) -> None:
    """A project with apps in ``src/<pkg>`` and config in ``config/``: the app and its package import work."""
    project = tmp_path / "home-automations"
    write_file(project / "pyproject.toml", '[project]\nname = "mypkg"\nversion = "0.1.0"\n')
    write_file(project / "src" / "mypkg" / "__init__.py", "")
    write_file(project / "src" / "mypkg" / "helpers.py", 'GREETING = "greeter started from mypkg"\n')
    write_file(project / "src" / "mypkg" / "greeter.py", PACKAGE_GREETER_APP)
    write_file(
        project / "config" / "hassette.toml",
        textwrap.dedent(
            """
            [hassette.apps]
            directory = "../src/mypkg"

            [hassette.apps.greeter]
            filename = "greeter.py"
            class_name = "Greeter"
            """
        ),
    )

    run = start_hassette(project, ha_container)
    try:
        app = wait_for_running_app(run, "Greeter")
    finally:
        exit_code = stop(run)

    assert app["app_key"] == "greeter"
    assert exit_code == 0, run.log_path.read_text()
    log = run.log_path.read_text()
    # core.py logs "Apps directory: <path>" at startup
    assert f"Apps directory: {project / 'src' / 'mypkg'}" in log
    assert "greeter started from mypkg" in log
