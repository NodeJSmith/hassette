"""Integration tests for Docker container behavior.

These tests verify that the Docker container correctly finds and installs
user's requirements.txt files from mounted volumes.
"""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

DOCKER_IMAGE = os.getenv("HASSETTE_TEST_IMAGE", "hassette:test")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed"),
]


def run_hassette_container(
    *,
    volumes: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run the hassette Docker image with ``--version`` and return the completed process."""
    cmd = ["docker", "run", "--rm"]
    for vol in volumes or []:
        cmd.extend(["-v", vol])
    merged_env = {
        "HASSETTE__APPS__DIRECTORY": "/apps",
        "HASSETTE__TOKEN": "test_token",
        "HASSETTE__BASE_URL": "http://test",
    }
    merged_env.update(env or {})
    for key, value in merged_env.items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.extend([DOCKER_IMAGE, "--version"])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def run_requirements_container(
    apps_dir: Path, *, extra_env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the container with INSTALL_DEPS=1 and a read-only apps mount, returning (result, combined output)."""
    env = {"HASSETTE__INSTALL_DEPS": "1"}
    if extra_env:
        env.update(extra_env)
    result = run_hassette_container(volumes=[f"{apps_dir}:/apps:ro"], env=env)
    return result, result.stderr + result.stdout


def run_project_container(project_dir: Path, *, timeout: int = 120) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the container with PROJECT_DIR pointing to the mounted project, returning (result, combined output)."""
    result = run_hassette_container(
        volumes=[f"{project_dir}:/apps"],
        env={"HASSETTE__PROJECT_DIR": "/apps"},
        timeout=timeout,
    )
    return result, result.stderr + result.stdout


def create_project_package(project_dir: Path, pyproject_content: str) -> None:
    """Write pyproject.toml, create a minimal package, and run ``uv lock``."""
    (project_dir / "pyproject.toml").write_text(pyproject_content)
    pkg_dir = project_dir / "test_proj"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    subprocess.run(["uv", "lock", "--directory", str(project_dir)], check=True, capture_output=True)


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
        timeout=30,
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
    """Test that requirements.txt in both /config and /apps are found."""
    config_dir = tmp_path / "config"
    apps_dir = tmp_path / "apps"
    config_dir.mkdir()
    apps_dir.mkdir()

    (config_dir / "requirements.txt").write_text("pyyaml>=6.0\n")
    (apps_dir / "requirements.txt").write_text("httpx>=0.25\n")

    result = run_hassette_container(
        volumes=[f"{config_dir}:/config:ro", f"{apps_dir}:/apps:ro"],
        env={"HASSETTE__CONFIG_DIR": "/config", "HASSETTE__INSTALL_DEPS": "1"},
    )
    output = result.stderr + result.stdout

    assert output.count("Installing requirements from") >= 2, f"Not all requirements found. Output:\n{output}"


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

    result = run_hassette_container(volumes=[f"{apps_dir}:/apps:ro"])
    output = result.stderr + result.stdout

    assert result.returncode == 0
    assert "requirements install: disabled" in output
    assert "Installing requirements from" not in output


def test_docker_constraint_conflict(tmp_path: Path):
    """Test that a requirements.txt conflicting with constraints fails with a clear error."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()

    # aiohttp==3.0.0 conflicts with hassette's aiohttp>=3.9 constraint
    (apps_dir / "requirements.txt").write_text("aiohttp==3.0.0\n")

    result, output = run_requirements_container(apps_dir)

    assert result.returncode != 0, f"Expected non-zero exit for conflict. Output:\n{output}"
    assert "DEPENDENCY CONFLICT" in output, f"Expected DEPENDENCY CONFLICT banner. Output:\n{output}"


def test_docker_project_install_with_lockfile(docker_project_dir: Path):
    """Test that a project with uv.lock triggers the export-then-install path."""
    create_project_package(
        docker_project_dir,
        '[project]\nname = "test-proj"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\ndependencies = []\n'
        '\n[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n',
    )
    result, output = run_project_container(docker_project_dir)

    assert result.returncode == 0, f"Project install failed. Output:\n{output}"
    assert "project install: complete" in output


def test_docker_project_install_without_build_system(docker_project_dir: Path):
    """Test that a project without [build-system] still installs via uv's default backend."""
    create_project_package(
        docker_project_dir,
        '[project]\nname = "test-proj"\nversion = "0.1.0"\nrequires-python = ">=3.11"\ndependencies = []\n',
    )
    result, output = run_project_container(docker_project_dir)

    assert result.returncode == 0, f"Project without [build-system] should still work. Output:\n{output}"
    assert "project install: complete" in output


def test_docker_project_without_lockfile_warns(docker_project_dir: Path):
    """Test that pyproject.toml without uv.lock logs a warning to run uv lock."""
    (docker_project_dir / "pyproject.toml").write_text(
        '[project]\nname = "test-proj"\nversion = "0.1.0"\ndependencies = []\n'
    )
    result, output = run_project_container(docker_project_dir, timeout=60)

    assert result.returncode == 0, f"Container should still start. Output:\n{output}"
    assert "uv lock" in output, f"Expected lockfile warning. Output:\n{output}"


def test_docker_project_install_with_real_dep(docker_project_dir: Path):
    """Test that a project with an actual dependency gets it installed through constraints."""
    create_project_package(
        docker_project_dir,
        '[project]\nname = "test-proj"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\ndependencies = ["tabulate>=0.9"]\n'
        '\n[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n',
    )
    result, output = run_project_container(docker_project_dir)

    assert result.returncode == 0, f"Project install with real dep failed. Output:\n{output}"
    assert "project install: complete" in output


def test_docker_project_constraint_conflict(docker_project_dir: Path):
    """Test that a project whose lockfile conflicts with hassette's constraints fails with a clear error."""
    # aiohttp==3.0.0 conflicts with hassette's aiohttp>=3.9 constraint
    create_project_package(
        docker_project_dir,
        '[project]\nname = "test-proj"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\ndependencies = ["aiohttp==3.0.0"]\n'
        '\n[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n',
    )
    result, output = run_project_container(docker_project_dir)

    assert result.returncode != 0, f"Expected non-zero exit for project constraint conflict. Output:\n{output}"
    assert "DEPENDENCY CONFLICT" in output, f"Expected DEPENDENCY CONFLICT banner. Output:\n{output}"


def test_docker_no_project_no_deps_starts_clean(tmp_path: Path):
    """Test that a container with no project and INSTALL_DEPS unset starts cleanly."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()

    result = run_hassette_container(volumes=[f"{apps_dir}:/apps:ro"])
    output = result.stderr + result.stdout

    assert result.returncode == 0, f"Clean start failed. Output:\n{output}"
    assert "project install: skipped" in output
    assert "requirements install: disabled" in output
