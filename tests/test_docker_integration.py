"""Integration tests for Docker container behavior.

These tests verify that the Docker entrypoint finds and installs the user's dependencies from the
config volume, and halts instead of hot-looping on an unrecoverable startup error. The container's
args default to ``--check``, so the final ``hassette run`` prints the resolved locations and exits
instead of starting the server.
"""

import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tests.support.docker import (
    ADDON,
    ADDON_REMEDY,
    CONFLICTING_REQUIREMENT,
    CONTAINER_TIMEOUT,
    DEGRADED_BANNER,
    DOCKER_CLEANUP_TIMEOUT,
    DOCKER_STOP_GRACE_SECS,
    HALT_BANNER,
    MAX_HALT_STOP_SECS,
    NETWORK_DOWN_UV_SHIM,
    NO_RETRY,
    OFFLINE_RETRY_MESSAGE,
    PROJECT_CONTAINER_TIMEOUT,
    UV_FAIL_FAST,
    create_project_package,
    installed_distributions,
    project_pyproject,
    run_hassette_container,
    run_project_container_and_diff,
    write_requirements,
)

# A wheel URL that returns 404: uv prints "Failed to fetch" for it too, but it's a dependency error, not the network
MISSING_WHEEL_REQUIREMENT = "foo @ https://files.pythonhosted.org/packages/xx/nope/foo-1.0-py3-none-any.whl"

# pydantic<2 is in no constraint line; it conflicts only through hassette's dependency tree
TRANSITIVE_CONFLICTING_REQUIREMENT = "pydantic<2"
CONFLICTING_REQUIREMENTS = [
    pytest.param(CONFLICTING_REQUIREMENT, id="direct"),
    pytest.param(TRANSITIVE_CONFLICTING_REQUIREMENT, id="transitive"),
]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed"),
]


def run_requirements_container(
    apps_dir: Path, *, env: dict[str, str] | None = None, network: str | None = None
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the container with INSTALL_DEPS=1 and apps mounted read-only at /config/apps."""
    return run_hassette_container(
        volumes=[f"{apps_dir}:/config/apps:ro"],
        env={"HASSETTE_DOCKER_INSTALL_DEPS": "1", **(env or {})},
        network=network,
    )


def run_project_container(
    project_dir: Path, *, timeout: int = PROJECT_CONTAINER_TIMEOUT, env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the container with the project mounted as the config volume, found by walking up from /config/apps."""
    return run_hassette_container(volumes=[f"{project_dir}:/config"], env=env, timeout=timeout)


def test_docker_installs_user_requirements(tmp_path: Path):
    """Test that Docker container finds and installs user requirements.txt."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    (apps_dir / "requirements.txt").write_text("requests>=2.28\n")

    (apps_dir / "test_app.py").write_text("""
from hassette import App, AppConfig

class TestApp(App[AppConfig]):
    async def on_initialize(self):
        # Try to import the required package
        import requests
        self.logger.info(f"requests version: {requests.__version__}")
""")

    result, output = run_requirements_container(apps_dir)

    assert "Installing requirements from" in output, f"Requirements not installed. Output:\n{output}"
    assert "requirements.txt" in output
    assert result.returncode == 0


def test_docker_finds_nested_requirements(tmp_path: Path):
    """Test that requirements.txt in subdirectories are found."""
    apps_dir = tmp_path / "apps"
    (apps_dir / "app1" / "subdir").mkdir(parents=True)
    (apps_dir / "app1" / "subdir" / "requirements.txt").write_text("httpx>=0.25\n")

    result, output = run_requirements_container(apps_dir)

    assert result.returncode == 0, f"Container exited with {result.returncode}. Output:\n{output}"
    assert "Installing requirements from" in output
    assert "requirements.txt" in output


def test_docker_installs_from_config_and_apps(tmp_path: Path):
    """Test that requirements.txt in both the config dir and an apps dir outside it are found."""
    config_dir = tmp_path / "config"
    apps_dir = tmp_path / "apps"
    config_dir.mkdir()
    apps_dir.mkdir()

    (config_dir / "requirements.txt").write_text("pyyaml>=6.0\n")
    (apps_dir / "requirements.txt").write_text("httpx>=0.25\n")

    _, output = run_hassette_container(
        volumes=[f"{config_dir}:/config:ro", f"{apps_dir}:/srv/apps:ro"],
        env={"HASSETTE__APPS__DIRECTORY": "/srv/apps", "HASSETTE_DOCKER_INSTALL_DEPS": "1"},
    )

    assert output.count("Installing requirements from") == 2, f"Expected exactly 2 installs. Output:\n{output}"


def test_docker_skips_empty_requirements(tmp_path: Path):
    """Test that empty requirements.txt files are skipped by the -s guard."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()

    # Empty requirements.txt in a subdirectory — fd finds it but -s guard skips it
    empty_dir = apps_dir / "emptyapp"
    empty_dir.mkdir()
    (empty_dir / "requirements.txt").touch()

    # Non-empty requirements.txt — should be installed
    (apps_dir / "requirements.txt").write_text("requests\n")

    _, output = run_requirements_container(apps_dir)

    assert output.count("Installing requirements from") == 1, f"Expected 1 install. Output:\n{output}"


def test_docker_handles_missing_requirements(tmp_path: Path):
    """Test that Docker starts successfully even without requirements.txt."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()

    (apps_dir / "test_app.py").write_text("""
from hassette import App, AppConfig

class TestApp(App[AppConfig]):
    async def on_initialize(self):
        pass
""")

    result, output = run_requirements_container(apps_dir)

    assert result.returncode == 0
    assert "requirements install: complete (0 file(s))" in output


def test_docker_installs_requirements_dev_variants(tmp_path: Path):
    """Test that requirements-dev.txt is NOT installed (fd pattern is exact match only)."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()

    (apps_dir / "requirements.txt").write_text("requests\n")
    (apps_dir / "requirements-dev.txt").write_text("pytest\n")

    _, output = run_requirements_container(apps_dir)

    assert output.count("Installing requirements from") == 1
    assert "requirements.txt" in output
    assert "requirements-dev.txt" not in output


def test_docker_skips_requirements_by_default(tmp_path: Path):
    """Test that requirements are NOT installed when INSTALL_DEPS is unset (default-off)."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    (apps_dir / "requirements.txt").write_text("requests\n")

    result, output = run_hassette_container(volumes=[f"{apps_dir}:/config/apps:ro"])

    assert result.returncode == 0
    assert "requirements install: disabled" in output
    assert "Installing requirements from" not in output


@pytest.mark.parametrize("requirement", CONFLICTING_REQUIREMENTS)
def test_docker_constraint_conflict(tmp_path: Path, requirement: str):
    """Test that a requirements.txt conflicting with hassette's dependencies fails with a clear error."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()

    (apps_dir / "requirements.txt").write_text(f"{requirement}\n")

    result, output = run_requirements_container(apps_dir, env=NO_RETRY)

    assert result.returncode == 1, f"Expected exit 1 for conflict. Output:\n{output}"
    assert "DEPENDENCY CONFLICT" in output, f"Expected DEPENDENCY CONFLICT banner. Output:\n{output}"
    assert HALT_BANNER in output


@pytest.mark.parametrize(
    ("pyproject_content", "expected_distributions"),
    [
        pytest.param(project_pyproject(), {"test_proj"}, id="with_lockfile"),
        pytest.param(project_pyproject(build_system=False), {"test_proj"}, id="without_build_system"),
        pytest.param(project_pyproject(["tabulate>=0.9"]), {"test_proj", "tabulate"}, id="with_real_dep"),
    ],
)
def test_docker_project_install_succeeds(
    docker_project_dir: Path, pyproject_content: str, expected_distributions: set[str]
):
    """Test that a locked project and its dependencies install via the export-then-install path.

    Covers a bare project, one without ``[build-system]`` (uv's default backend), and one with a
    real dependency installed through constraints.
    """
    create_project_package(docker_project_dir, pyproject_content)
    result, output, diff_lines = run_project_container_and_diff(docker_project_dir)

    assert result.returncode == 0, f"Project install failed. Output:\n{output}"
    missing = expected_distributions - installed_distributions(diff_lines)
    assert not missing, f"Not installed: {sorted(missing)}. Output:\n{output}"


def test_docker_project_install_cleans_up_tmp_build_dir(docker_project_dir: Path):
    """Test that /tmp/project-build.* doesn't leak after project install (regression for #2329).

    The project-install path's EXIT trap never fires on the happy path because docker_start.sh
    ends in `exec hassette run`, which replaces the shell process instead of exiting it — so
    cleanup must happen explicitly before the exec. Uses `docker diff` (rather than --rm) so the
    container's final filesystem state can be inspected after it exits.
    """
    create_project_package(docker_project_dir, project_pyproject())
    result, output, diff_lines = run_project_container_and_diff(docker_project_dir)

    assert result.returncode == 0, f"Project install failed. Output:\n{output}"
    leaked = [line for line in diff_lines if "/project-build." in line]
    assert not leaked, f"Leftover project-build tmp dir(s) found: {leaked}"


def test_docker_project_install_skips_virtualenv_dir(docker_project_dir: Path):
    """Test that the project's in-tree .venv isn't copied into the build dir (regression for #2773).

    The .venv holds a file the container user can't read, so copying it would fail the install.
    """
    create_project_package(docker_project_dir, project_pyproject())
    venv_dir = docker_project_dir / ".venv"
    venv_dir.mkdir()
    unreadable = venv_dir / "unreadable"
    unreadable.write_text("")
    unreadable.chmod(0)

    result, output = run_project_container(docker_project_dir)

    assert result.returncode == 0, f"Project install failed. Output:\n{output}"
    assert "project install: complete" in output, output


def test_docker_project_install_keeps_nested_subpackage_named_like_a_venv(docker_project_dir: Path):
    """Test that only the project-root venv is skipped, not a subpackage that shares its name."""
    create_project_package(docker_project_dir, project_pyproject())
    subpkg = docker_project_dir / "test_proj" / "venv"
    subpkg.mkdir()
    (subpkg / "__init__.py").write_text("")

    result, output, diff_lines = run_project_container_and_diff(docker_project_dir)

    assert result.returncode == 0, f"Project install failed. Output:\n{output}"
    installed = [line for line in diff_lines if line.endswith("/site-packages/test_proj/venv/__init__.py")]
    assert installed, f"Nested test_proj/venv subpackage was not installed. Diff:\n{diff_lines}"


def test_docker_project_without_lockfile_warns(docker_project_dir: Path):
    """Test that pyproject.toml without uv.lock logs a warning to run uv lock."""
    (docker_project_dir / "pyproject.toml").write_text(
        '[project]\nname = "test-proj"\nversion = "0.1.0"\ndependencies = []\n'
    )
    result, output = run_project_container(docker_project_dir, timeout=CONTAINER_TIMEOUT)

    assert result.returncode == 0, f"Container should still start. Output:\n{output}"
    assert "uv lock" in output, f"Expected lockfile warning. Output:\n{output}"


@pytest.mark.parametrize("requirement", CONFLICTING_REQUIREMENTS)
def test_docker_project_constraint_conflict(docker_project_dir: Path, requirement: str):
    """Test that a project whose lockfile conflicts with hassette's dependencies fails with a clear error."""
    create_project_package(docker_project_dir, project_pyproject([requirement]))
    result, output = run_project_container(docker_project_dir, env=NO_RETRY)

    assert result.returncode == 1, f"Expected exit 1 for project constraint conflict. Output:\n{output}"
    assert "DEPENDENCY CONFLICT" in output, f"Expected DEPENDENCY CONFLICT banner. Output:\n{output}"


def test_docker_no_project_no_deps_starts_clean(tmp_path: Path):
    """Test that a container with no project and INSTALL_DEPS unset starts cleanly."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()

    result, output = run_hassette_container(volumes=[f"{apps_dir}:/config/apps:ro"])

    assert result.returncode == 0, f"Clean start failed. Output:\n{output}"
    assert "project install: skipped" in output
    assert "requirements install: disabled" in output


def test_docker_apps_default_to_the_config_volume():
    """With no apps setting, the apps dir is <config dir>/apps."""
    result, output = run_hassette_container()

    assert result.returncode == 0, output
    assert "APPS_DIR=/config/apps" in output


def test_docker_finds_project_by_walking_up_from_the_apps_dir(docker_project_dir: Path):
    """A hautomate-style layout (project at /apps, apps in /apps/src/<pkg>) is found with no project setting."""
    create_project_package(docker_project_dir, project_pyproject(build_system=False))
    (docker_project_dir / "src" / "test_proj").mkdir(parents=True)

    result, output = run_hassette_container(
        volumes=[f"{docker_project_dir}:/apps"],
        env={"HASSETTE__APPS__DIRECTORY": "/apps/src/test_proj"},
        timeout=PROJECT_CONTAINER_TIMEOUT,
    )

    assert result.returncode == 0, output
    assert "project install: starting (from /apps)" in output


def test_docker_config_error_halts_with_exit_78():
    """An unknown key fails `hassette run --check`, which halts before installing anything."""
    result, output = run_hassette_container(env={"HASSETTE__APP_DIR": "/apps", **NO_RETRY})

    assert result.returncode == 78, output
    assert "HASSETTE__APP_DIR (from environment)" in output
    assert HALT_BANNER in output
    assert "docker compose up -d" in output
    assert "project install" not in output


def test_docker_file_config_error_gets_the_recreate_remedy(tmp_path: Path):
    """A config error from a mounted file gets the same recreate remedy as one from the environment."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "hassette.toml").write_text("bogus = 1\n")

    result, output = run_hassette_container(volumes=[f"{config_dir}:/config:ro"], env=NO_RETRY)

    assert result.returncode == 78, output
    assert "bogus (from /config/hassette.toml)" in output
    assert "docker compose up -d" in output


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_docker_help_and_version_skip_the_check(flag: str):
    """Help and version args print and exit 0 without a config check or any install, even with a bad config."""
    result, output = run_hassette_container(env={"HASSETTE__APP_DIR": "/apps", **NO_RETRY}, args=[flag])

    assert result.returncode == 0, output
    assert HALT_BANNER not in output
    assert "project install" not in output


def test_docker_parent_relative_apps_dir_is_normalized(tmp_path: Path):
    """``directory = "../apps"`` in /config/hassette.toml is the /apps volume, not a path inside /config."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "hassette.toml").write_text('[apps]\ndirectory = "../apps"\n')
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    (apps_dir / "my_app.py").write_text("")

    result, output = run_hassette_container(volumes=[f"{config_dir}:/config:ro", f"{apps_dir}:/apps:ro"])

    assert result.returncode == 0, output
    assert "config checked (config dir /config, apps dir /apps)" in output


def test_docker_config_dir_arg_reaches_both_invocations(tmp_path: Path):
    """`--config-dir` passed as container args reaches the check and the final `hassette run`."""
    config_dir = tmp_path / "alt"
    config_dir.mkdir()

    result, output = run_hassette_container(volumes=[f"{config_dir}:/alt:ro"], args=["--check", "--config-dir", "/alt"])

    assert result.returncode == 0, output
    assert "config checked (config dir /alt, apps dir /alt/apps)" in output
    assert "CONFIG_DIR=/alt" in output


def stop_container_once_logged(container_name: str, marker: str) -> tuple[float, int]:
    """Wait for `marker` in the container's log, then `docker stop` it.

    Returns:
        (seconds the stop took, the container's exit code)
    """
    deadline = time.monotonic() + CONTAINER_TIMEOUT
    while marker not in (logs := docker_logs(container_name)):
        assert time.monotonic() < deadline, logs
        time.sleep(0.5)

    started = time.monotonic()
    subprocess.run(
        ["docker", "stop", "-t", str(DOCKER_STOP_GRACE_SECS), container_name],
        check=True,
        capture_output=True,
        timeout=CONTAINER_TIMEOUT,
    )
    stop_secs = time.monotonic() - started
    exit_code = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.ExitCode}}", container_name],
        check=True,
        capture_output=True,
        text=True,
        timeout=DOCKER_CLEANUP_TIMEOUT,
    ).stdout.strip()
    return stop_secs, int(exit_code)


@contextmanager
def detached_container(**kwargs: Any) -> Iterator[str]:
    """Start a detached container (``run_hassette_container`` kwargs) and yield its name; it's removed on exit."""
    container_name = f"hassette-detached-test-{uuid.uuid4().hex[:12]}"
    try:
        run_hassette_container(name=container_name, remove=False, detach=True, **kwargs)
        yield container_name
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=DOCKER_CLEANUP_TIMEOUT)


def test_docker_stop_ends_a_halt_promptly_with_exit_0():
    """The halt's idle is interruptible: `docker stop` returns well before the stop timeout, and exits 0."""
    with detached_container(env={"HASSETTE__APP_DIR": "/apps", "HASSETTE_DOCKER_RETRY_DELAY": "300"}) as name:
        stop_secs, exit_code = stop_container_once_logged(name, HALT_BANNER)

    assert stop_secs < MAX_HALT_STOP_SECS
    assert exit_code == 0


def test_docker_stop_during_the_install_exits_0_promptly(tmp_path: Path):
    """A stop mid-install ends the install at once and exits 0, not 143 (Supervisor logs 143 as a failure)."""
    apps_dir = write_requirements(tmp_path, "tabulate")
    # With no network and uv's default retries, the install keeps retrying the index for ~25s
    with detached_container(
        volumes=[f"{apps_dir}:/config/apps:ro"], env={"HASSETTE_DOCKER_INSTALL_DEPS": "1"}, network="none"
    ) as name:
        stop_secs, exit_code = stop_container_once_logged(name, "Installing requirements from")
        logs = docker_logs(name)

    assert stop_secs < MAX_HALT_STOP_SECS
    assert exit_code == 0
    # the stop landed mid-install, not after the install had already failed into the halt idle
    assert HALT_BANNER not in logs


def test_addon_network_failure_retries_offline_from_the_cache(tmp_path: Path):
    """Under the add-on, a network failure retries the install with --offline, and a passing retry starts normally."""
    # pydantic is in the image's venv, so the offline retry passes with an empty cache
    apps_dir = write_requirements(tmp_path, "pydantic")
    shim = tmp_path / "uv"
    shim.write_text(NETWORK_DOWN_UV_SHIM)
    shim.chmod(0o755)

    result, output = run_hassette_container(
        volumes=[f"{apps_dir}:/config/apps:ro", f"{shim}:/app/.venv/bin/uv:ro"],
        env={"HASSETTE_DOCKER_INSTALL_DEPS": "1", **ADDON},
    )

    assert result.returncode == 0, output
    assert OFFLINE_RETRY_MESSAGE in output
    assert "Installed from the uv cache." in output
    assert DEGRADED_BANNER not in output


def test_addon_failed_offline_retry_starts_degraded_with_a_banner(tmp_path: Path):
    """Under the add-on, with no network and nothing cached, hassette still starts and the banner names the install."""
    apps_dir = write_requirements(tmp_path, "tabulate")

    result, output = run_hassette_container(
        volumes=[f"{apps_dir}:/config/apps:ro"],
        env={"HASSETTE_DOCKER_INSTALL_DEPS": "1", **ADDON, **UV_FAIL_FAST},
        network="none",
    )

    assert result.returncode == 0, output
    assert OFFLINE_RETRY_MESSAGE in output
    assert DEGRADED_BANNER in output
    assert "    - /config/apps/requirements.txt" in output
    assert HALT_BANNER not in output


def test_addon_failed_offline_retry_skips_the_rest_of_the_project_install(docker_project_dir: Path):
    """A project step skipped offline stops the later project steps, and later installs go straight to --offline."""
    create_project_package(docker_project_dir, project_pyproject(["tabulate>=0.9"]))
    (docker_project_dir / "apps").mkdir()
    (docker_project_dir / "apps" / "requirements.txt").write_text("requests-toolbelt\n")  # not in the image's venv

    result, output = run_hassette_container(
        volumes=[f"{docker_project_dir}:/config"],
        env={"HASSETTE_DOCKER_INSTALL_DEPS": "1", **ADDON, **UV_FAIL_FAST},
        network="none",
        timeout=PROJECT_CONTAINER_TIMEOUT,
    )

    assert result.returncode == 0, output
    assert "    - your project (/config/uv.lock)" in output
    assert "    - /config/apps/requirements.txt" in output
    assert "project install: installing project package" not in output
    assert "project install: complete" not in output
    assert output.count(OFFLINE_RETRY_MESSAGE) == 1, output
    assert "The package index was unreachable earlier" in output


def test_addon_http_error_status_halts_instead_of_starting_degraded(tmp_path: Path):
    """A 404 dependency URL is a dependency error, not the network: it halts under the add-on, with no offline retry."""
    apps_dir = write_requirements(tmp_path, MISSING_WHEEL_REQUIREMENT)

    result, output = run_requirements_container(apps_dir, env=ADDON)

    assert result.returncode == 1, output
    assert HALT_BANNER in output
    assert OFFLINE_RETRY_MESSAGE not in output


def test_unrecognized_runtime_warns_and_keeps_docker_behavior():
    """An unknown HASSETTE_DOCKER_RUNTIME value is named in a warning, and the Docker remedies apply."""
    result, output = run_hassette_container(
        env={"HASSETTE_DOCKER_RUNTIME": "add-on", "HASSETTE__APP_DIR": "/apps", **NO_RETRY}
    )

    assert result.returncode == 78, output
    assert "HASSETTE_DOCKER_RUNTIME='add-on' is not recognized" in output
    assert "docker compose up -d" in output


def test_docker_network_failure_halts_as_a_network_error(tmp_path: Path):
    """Without the add-on runtime, a network failure halts, named as the network rather than a dependency conflict."""
    apps_dir = write_requirements(tmp_path, "tabulate")

    result, output = run_requirements_container(apps_dir, env={**NO_RETRY, **UV_FAIL_FAST}, network="none")

    assert result.returncode == 1, output
    assert f"{HALT_BANNER}: the package index couldn't be reached" in output
    assert "Check the container's network access" in output
    assert "DEPENDENCY CONFLICT" not in output
    assert OFFLINE_RETRY_MESSAGE not in output


def test_addon_constraint_conflict_halts_without_an_offline_retry(tmp_path: Path):
    """A resolution conflict halts under the add-on too, with the add-on remedy and no offline retry."""
    apps_dir = write_requirements(tmp_path, CONFLICTING_REQUIREMENT)

    result, output = run_requirements_container(apps_dir, env=ADDON)

    assert result.returncode == 1, output
    assert "DEPENDENCY CONFLICT" in output
    assert ADDON_REMEDY in output
    assert OFFLINE_RETRY_MESSAGE not in output


def test_addon_config_error_gets_the_addon_remedy():
    """Under the add-on, a config error still halts with exit 78, and the remedy names the add-on page."""
    result, output = run_hassette_container(env={"HASSETTE__APP_DIR": "/apps", **ADDON})

    assert result.returncode == 78, output
    assert ADDON_REMEDY in output
    assert "docker compose" not in output


def docker_logs(container_name: str) -> str:
    logs = subprocess.run(
        ["docker", "logs", container_name], capture_output=True, text=True, timeout=DOCKER_CLEANUP_TIMEOUT
    )
    return logs.stdout + logs.stderr
