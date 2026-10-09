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
from collections.abc import Iterator
from pathlib import Path

import pytest

DEFAULT_DOCKER_IMAGE = "hassette:test"
DOCKER_IMAGE = os.getenv("HASSETTE_TEST_IMAGE", DEFAULT_DOCKER_IMAGE)

CONTAINER_TIMEOUT = 60
PROJECT_CONTAINER_TIMEOUT = 120
UV_LOCK_TIMEOUT = 60
DOCKER_CLEANUP_TIMEOUT = 30

FAKE_TOKEN = "test_token"
FAKE_BASE_URL = "http://test"
BASE_CONTAINER_ENV = {
    "HASSETTE__TOKEN": FAKE_TOKEN,
    "HASSETTE__BASE_URL": FAKE_BASE_URL,
}

# aiohttp==3.0.0 conflicts with hassette's aiohttp>=3.9 constraint
CONFLICTING_REQUIREMENT = "aiohttp==3.0.0"

HATCHLING_BUILD_SYSTEM = '\n[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
NO_RETRY = {"HASSETTE_DOCKER_RETRY_DELAY": "0"}

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
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the hassette Docker image with `args` (default ``--check``), returning (result, combined output).

    Pass ``name`` and ``remove=False`` to keep the stopped container around for inspection
    (e.g. via ``docker diff``) instead of letting ``--rm`` discard it on exit.
    """
    cmd = ["docker", "run"]
    if remove:
        cmd.append("--rm")
    if name:
        cmd.extend(["--name", name])
    for vol in volumes or []:
        cmd.extend(["-v", vol])
    merged_env = {**BASE_CONTAINER_ENV, **(env or {})}
    for key, value in merged_env.items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.extend([DOCKER_IMAGE, *(args if args is not None else ["--check"])])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result, result.stderr + result.stdout


def run_requirements_container(
    apps_dir: Path, *, env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the container with INSTALL_DEPS=1 and apps mounted read-only at /config/apps."""
    return run_hassette_container(
        volumes=[f"{apps_dir}:/config/apps:ro"], env={"HASSETTE_DOCKER_INSTALL_DEPS": "1", **(env or {})}
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


def project_pyproject(dependencies: str = "[]", *, build_system: bool = True) -> str:
    """Return a minimal ``test-proj`` pyproject.toml, optionally with a hatchling ``[build-system]``."""
    content = (
        f'[project]\nname = "test-proj"\nversion = "0.1.0"\nrequires-python = ">=3.11"\ndependencies = {dependencies}\n'
    )
    return content + HATCHLING_BUILD_SYSTEM if build_system else content


@pytest.mark.parametrize(
    "pyproject_content",
    [
        pytest.param(project_pyproject(), id="with_lockfile"),
        pytest.param(project_pyproject(build_system=False), id="without_build_system"),
        pytest.param(project_pyproject('["tabulate>=0.9"]'), id="with_real_dep"),
    ],
)
def test_docker_project_install_succeeds(docker_project_dir: Path, pyproject_content: str):
    """Test that a locked project installs via the export-then-install path.

    Covers a bare project, one without ``[build-system]`` (uv's default backend), and one with a
    real dependency installed through constraints.
    """
    create_project_package(docker_project_dir, pyproject_content)
    result, output = run_project_container(docker_project_dir)

    assert result.returncode == 0, f"Project install failed. Output:\n{output}"
    assert "project install: complete" in output


def test_docker_project_install_cleans_up_tmp_build_dir(docker_project_dir: Path):
    """Test that /tmp/project-build.* doesn't leak after project install (regression for #2329).

    The project-install path's EXIT trap never fires on the happy path because docker_start.sh
    ends in `exec hassette run`, which replaces the shell process instead of exiting it — so
    cleanup must happen explicitly before the exec. Uses `docker diff` (rather than --rm) so the
    container's final filesystem state can be inspected after it exits.
    """
    create_project_package(docker_project_dir, project_pyproject())

    container_name = f"hassette-tmp-leak-test-{os.getpid()}"
    try:
        result, output = run_hassette_container(
            volumes=[f"{docker_project_dir}:/config"],
            timeout=PROJECT_CONTAINER_TIMEOUT,
            name=container_name,
            remove=False,
        )
        assert result.returncode == 0, f"Project install failed. Output:\n{output}"

        diff = subprocess.run(
            ["docker", "diff", container_name],
            capture_output=True,
            text=True,
            timeout=DOCKER_CLEANUP_TIMEOUT,
            check=True,
        )
        leaked = [line for line in diff.stdout.splitlines() if "/tmp/project-build." in line]
        assert not leaked, f"Leftover project-build tmp dir(s) found:\n{diff.stdout}"
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=DOCKER_CLEANUP_TIMEOUT)


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
    create_project_package(docker_project_dir, project_pyproject(f'["{CONFLICTING_REQUIREMENT}"]'))
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


def test_docker_stop_ends_a_halt_promptly():
    """The halt's idle is interruptible: `docker stop` returns well before the stop timeout."""
    container_name = f"hassette-halt-stop-test-{os.getpid()}"
    try:
        subprocess.run(
            [
                "docker", "run", "-d", "--name", container_name,
                "-e", "HASSETTE__APP_DIR=/apps", "-e", "HASSETTE_DOCKER_RETRY_DELAY=300",
                DOCKER_IMAGE, "--check",
            ],
            check=True, capture_output=True, timeout=DOCKER_CLEANUP_TIMEOUT,
        )  # fmt: skip
        deadline = time.monotonic() + 60
        while "HASSETTE CAN'T START" not in (logs := docker_logs(container_name)):
            assert time.monotonic() < deadline, logs
            time.sleep(0.5)

        started = time.monotonic()
        subprocess.run(["docker", "stop", "-t", "30", container_name], check=True, capture_output=True, timeout=60)

        assert time.monotonic() - started < 10
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=DOCKER_CLEANUP_TIMEOUT)


def docker_logs(container_name: str) -> str:
    logs = subprocess.run(
        ["docker", "logs", container_name], capture_output=True, text=True, timeout=DOCKER_CLEANUP_TIMEOUT
    )
    return logs.stdout + logs.stderr
