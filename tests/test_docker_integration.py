"""Integration tests for Docker container behavior.

These tests verify that the Docker entrypoint finds and installs the user's dependencies from the
config volume, and halts instead of hot-looping on an unrecoverable startup error. The container's
args default to ``--check``, so the final ``hassette run`` prints the resolved locations and exits
instead of starting the server.
"""

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

DEFAULT_DOCKER_IMAGE = "hassette:test"
DOCKER_IMAGE = os.getenv("HASSETTE_TEST_IMAGE", DEFAULT_DOCKER_IMAGE)

CONTAINER_TIMEOUT = 60
PROJECT_CONTAINER_TIMEOUT = 120
UV_LOCK_TIMEOUT = 60
DOCKER_CLEANUP_TIMEOUT = 30
# `docker stop` grace period, and how fast a halted container must stop within it
DOCKER_STOP_GRACE_SECS = 30
MAX_HALT_STOP_SECS = 10

BASE_CONTAINER_ENV = {
    "HASSETTE__TOKEN": "test_token",
    "HASSETTE__BASE_URL": "http://test",
}
NO_RETRY = {"HASSETTE_DOCKER_RETRY_DELAY": "0"}
# What the add-on glue sets (design/specs/129-ha-addon-v01 D4)
ADDON = {"HASSETTE_DOCKER_RUNTIME": "addon", "HASSETTE_DOCKER_PRUNE_UV_CACHE": "0", **NO_RETRY}
# With `--network none`, uv fails a fetch at once instead of retrying it for ~25s
UV_FAIL_FAST = {"UV_HTTP_RETRIES": "0"}
ADDON_REMEDY = "restart the add-on from its page"
DEGRADED_BANNER = "HASSETTE IS STARTING WITHOUT SOME DEPENDENCIES"
OFFLINE_RETRY_MESSAGE = "retrying from the uv cache (--offline)"
# A uv stand-in that fails every online run with uv's connection error and passes --offline runs to the real uv,
# so a test can exercise the offline retry without a stale cache (uv trusts a freshly cached index page offline).
# It's mounted over /app/.venv/bin/uv, which the activated venv puts ahead of the image's real uv at /bin/uv. The
# error text must match UV_NETWORK_ERROR_PATTERN in scripts/docker_start.sh.
NETWORK_DOWN_UV_SHIM = """#!/bin/sh
for arg in "$@"; do
    [ "$arg" = "--offline" ] && exec /bin/uv "$@"
done
echo "error: Request failed after 3 retries"
echo "  Caused by: Failed to fetch: \\`https://pypi.org/simple/pydantic/\\`"
echo "  Caused by: error sending request for url (https://pypi.org/simple/pydantic/)"
exit 2
"""
# A wheel URL that returns 404: uv prints "Failed to fetch" for it too, but it's a dependency error, not the network
MISSING_WHEEL_REQUIREMENT = "foo @ https://files.pythonhosted.org/packages/xx/nope/foo-1.0-py3-none-any.whl"

# aiohttp==3.0.0 conflicts with hassette's aiohttp>=3.9 constraint
CONFLICTING_REQUIREMENT = "aiohttp==3.0.0"
HATCHLING_BUILD_SYSTEM = '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed"),
]


def run_hassette_container(
    *,
    volumes: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: int = CONTAINER_TIMEOUT,
    name: str | None = None,
    remove: bool = True,
    args: list[str] | None = None,
    network: str | None = None,
    detach: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the hassette Docker image with `args` (default ``--check``), returning (result, combined output).

    Pass ``name`` and ``remove=False`` to keep the stopped container around for inspection
    (e.g. via ``docker diff``) instead of letting ``--rm`` discard it on exit. ``network="none"``
    cuts the container off from the package index. ``detach=True`` returns once the container starts,
    with the container ID as the output; read its log with ``docker_logs(name)``.
    """
    cmd = ["docker", "run"]
    if remove:
        cmd.append("--rm")
    if detach:
        cmd.append("-d")
    if name:
        cmd.extend(["--name", name])
    if network:
        cmd.extend(["--network", network])
    for vol in volumes or []:
        cmd.extend(["-v", vol])
    merged_env = {**BASE_CONTAINER_ENV, **(env or {})}
    for key, value in merged_env.items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.extend([DOCKER_IMAGE, *(args if args is not None else ["--check"])])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result, result.stderr + result.stdout


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


def create_project_package(project_dir: Path, pyproject_content: str) -> None:
    """Write pyproject.toml, create a minimal package, and run ``uv lock``."""
    (project_dir / "pyproject.toml").write_text(pyproject_content)
    pkg_dir = project_dir / "test_proj"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    subprocess.run(
        ["uv", "lock", "--directory", str(project_dir)], check=True, capture_output=True, timeout=UV_LOCK_TIMEOUT
    )


@pytest.fixture
def docker_project_dir() -> Iterator[Path]:
    """Temp directory for project-based Docker tests with UID-safe cleanup.

    The container's hassette user (UID 1000) creates build artifacts (egg-info, build/)
    that the CI runner (different UID) cannot delete. The teardown uses `docker run --user root`
    to chmod everything before rmtree.
    """
    tmpdir = tempfile.mkdtemp()
    project_dir = Path(tmpdir) / "project"
    project_dir.mkdir()
    yield project_dir
    # Fix ownership so rmtree can clean up container-created files
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "root",
            "--entrypoint",
            "chmod",
            "-v",
            f"{tmpdir}:/mnt",
            DOCKER_IMAGE,
            "-R",
            "777",
            "/mnt",
        ],
        capture_output=True,
        timeout=DOCKER_CLEANUP_TIMEOUT,
    )
    shutil.rmtree(tmpdir, ignore_errors=True)


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


def test_docker_constraint_conflict(tmp_path: Path):
    """Test that a requirements.txt conflicting with constraints fails with a clear error."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()

    (apps_dir / "requirements.txt").write_text(f"{CONFLICTING_REQUIREMENT}\n")

    result, output = run_requirements_container(apps_dir, env=NO_RETRY)

    assert result.returncode == 1, f"Expected exit 1 for conflict. Output:\n{output}"
    assert "DEPENDENCY CONFLICT" in output, f"Expected DEPENDENCY CONFLICT banner. Output:\n{output}"
    assert "HASSETTE CAN'T START" in output


def project_pyproject(dependencies: list[str] | None = None, *, build_system: bool = True) -> str:
    """Return a minimal ``test-proj`` pyproject.toml, optionally with a hatchling ``[build-system]``."""
    deps = ", ".join(f'"{dep}"' for dep in dependencies or [])
    content = f'[project]\nname = "test-proj"\nversion = "0.1.0"\nrequires-python = ">=3.11"\ndependencies = [{deps}]\n'
    if build_system:
        content += "\n" + HATCHLING_BUILD_SYSTEM
    return content


def run_project_container_and_diff(project_dir: Path) -> tuple[subprocess.CompletedProcess[str], str, list[str]]:
    """Run the project container, returning (result, combined output, ``docker diff`` lines).

    The container is kept until its filesystem changes are read, so a test can check what the
    entrypoint installed or left behind after the process exits.
    """
    container_name = f"hassette-project-test-{uuid.uuid4().hex[:12]}"
    try:
        result, output = run_hassette_container(
            volumes=[f"{project_dir}:/config"],
            timeout=PROJECT_CONTAINER_TIMEOUT,
            name=container_name,
            remove=False,
        )
        diff = subprocess.run(
            ["docker", "diff", container_name],
            capture_output=True,
            text=True,
            timeout=DOCKER_CLEANUP_TIMEOUT,
            check=True,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=DOCKER_CLEANUP_TIMEOUT)
    return result, output, diff.stdout.splitlines()


def installed_distributions(diff_lines: list[str]) -> set[str]:
    """Return the distributions whose ``.dist-info`` directory ``docker diff`` lines (``<A|C|D> <path>``) show as added.

    Every installed distribution gets a ``<name>-<version>.dist-info`` directory, whether it ships a
    package directory or a single module, so this doesn't depend on the distribution's layout.
    """
    added = (line.removeprefix("A ") for line in diff_lines if line.startswith("A "))
    return {
        entry.split("-", 1)[0]
        for path in added
        if "/site-packages/" in path
        and "/" not in (entry := path.split("/site-packages/", 1)[1])
        and entry.endswith(".dist-info")
    }


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


def test_docker_project_constraint_conflict(docker_project_dir: Path):
    """Test that a project whose lockfile conflicts with hassette's constraints fails with a clear error."""
    create_project_package(docker_project_dir, project_pyproject([CONFLICTING_REQUIREMENT]))
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
    assert "HASSETTE CAN'T START" in output
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
    assert "HASSETTE CAN'T START" not in output
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


def test_docker_stop_ends_a_halt_promptly_with_exit_0():
    """The halt's idle is interruptible: `docker stop` returns well before the stop timeout, and exits 0."""
    container_name = f"hassette-halt-stop-test-{uuid.uuid4().hex[:12]}"
    try:
        run_hassette_container(
            name=container_name,
            remove=False,
            detach=True,
            env={"HASSETTE__APP_DIR": "/apps", "HASSETTE_DOCKER_RETRY_DELAY": "300"},
        )
        stop_secs, exit_code = stop_container_once_logged(container_name, "HASSETTE CAN'T START")

        assert stop_secs < MAX_HALT_STOP_SECS
        assert exit_code == 0
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=DOCKER_CLEANUP_TIMEOUT)


def test_docker_stop_during_the_install_exits_0_promptly(tmp_path: Path):
    """A stop mid-install ends the install at once and exits 0, not 143 (Supervisor logs 143 as a failure)."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    (apps_dir / "requirements.txt").write_text("tabulate\n")
    container_name = f"hassette-install-stop-test-{uuid.uuid4().hex[:12]}"
    try:
        # With no network and uv's default retries, the install keeps retrying the index for ~25s
        run_hassette_container(
            volumes=[f"{apps_dir}:/config/apps:ro"],
            env={"HASSETTE_DOCKER_INSTALL_DEPS": "1"},
            name=container_name,
            remove=False,
            detach=True,
            network="none",
        )
        stop_secs, exit_code = stop_container_once_logged(container_name, "Installing requirements from")

        assert stop_secs < MAX_HALT_STOP_SECS
        assert exit_code == 0
        # the stop landed mid-install, not after the install had already failed into the halt idle
        assert "HASSETTE CAN'T START" not in docker_logs(container_name)
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=DOCKER_CLEANUP_TIMEOUT)


def write_requirements(tmp_path: Path, requirement: str) -> Path:
    """Create ``tmp_path/apps`` holding a one-line requirements.txt, and return the apps dir."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    (apps_dir / "requirements.txt").write_text(f"{requirement}\n")
    return apps_dir


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
    assert "HASSETTE CAN'T START" not in output


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
    assert "HASSETTE CAN'T START" in output
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
    assert "HASSETTE CAN'T START: the package index couldn't be reached" in output
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
