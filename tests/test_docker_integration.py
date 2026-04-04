"""Integration tests for Docker container behavior.

These tests verify that the Docker container correctly finds and installs
user's requirements.txt files from mounted volumes.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# Allow overriding the Docker image for testing
# Default to locally built image, can override with HASSETTE_TEST_IMAGE env var
DOCKER_IMAGE = os.getenv("HASSETTE_TEST_IMAGE", "hassette:test")


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed")
def test_docker_installs_user_requirements():
    """Test that Docker container finds and installs user requirements.txt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create a test app directory with requirements
        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()
        (apps_dir / "requirements.txt").write_text("requests>=2.28\n")

        # Create a simple app
        (apps_dir / "test_app.py").write_text("""
from hassette import App, AppConfig

class TestApp(App[AppConfig]):
    async def on_initialize(self):
        # Try to import the required package
        import requests
        self.logger.info(f"requests version: {requests.__version__}")
""")

        # Run Docker container with mounted volume
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{apps_dir}:/apps:ro",
                "-e",
                "HASSETTE__APP_DIR=/apps",
                "-e",
                "HASSETTE__TOKEN=test_token",
                "-e",
                "HASSETTE__BASE_URL=http://test",
                "-e",
                "HASSETTE__INSTALL_DEPS=1",
                DOCKER_IMAGE,
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stderr + result.stdout

        # Check that requirements were found and installed
        assert "Installing requirements from" in output, f"Requirements not installed. Output:\n{output}"
        assert "requirements.txt" in output
        assert result.returncode == 0


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed")
def test_docker_finds_nested_requirements():
    """Test that requirements.txt in subdirectories are found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create nested structure
        apps_dir = tmp_path / "apps"
        (apps_dir / "app1" / "subdir").mkdir(parents=True)
        (apps_dir / "app1" / "subdir" / "requirements.txt").write_text("httpx>=0.25\n")

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{apps_dir}:/apps:ro",
                "-e",
                "HASSETTE__APP_DIR=/apps",
                "-e",
                "HASSETTE__TOKEN=test_token",
                "-e",
                "HASSETTE__BASE_URL=http://test",
                "-e",
                "HASSETTE__INSTALL_DEPS=1",
                DOCKER_IMAGE,
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stderr + result.stdout
        assert result.returncode == 0, f"Container exited with {result.returncode}. Output:\n{output}"
        assert "Installing requirements from" in output
        assert "requirements.txt" in output


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed")
def test_docker_installs_from_config_and_apps():
    """Test that requirements.txt in both /config and /apps are found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create both config and apps directories
        config_dir = tmp_path / "config"
        apps_dir = tmp_path / "apps"
        config_dir.mkdir()
        apps_dir.mkdir()

        (config_dir / "requirements.txt").write_text("pyyaml>=6.0\n")
        (apps_dir / "requirements.txt").write_text("httpx>=0.25\n")

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{config_dir}:/config:ro",
                "-v",
                f"{apps_dir}:/apps:ro",
                "-e",
                "HASSETTE__APP_DIR=/apps",
                "-e",
                "HASSETTE__CONFIG_DIR=/config",
                "-e",
                "HASSETTE__TOKEN=test_token",
                "-e",
                "HASSETTE__BASE_URL=http://test",
                "-e",
                "HASSETTE__INSTALL_DEPS=1",
                DOCKER_IMAGE,
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stderr + result.stdout

        # Both requirements files should be installed
        assert output.count("Installing requirements from") >= 2, f"Not all requirements found. Output:\n{output}"


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed")
def test_docker_skips_empty_requirements():
    """Test that empty requirements.txt files are skipped by the -s guard."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        # Empty requirements.txt in a subdirectory — fd finds it but -s guard skips it
        empty_dir = apps_dir / "emptyapp"
        empty_dir.mkdir()
        (empty_dir / "requirements.txt").touch()

        # Non-empty requirements.txt — should be installed
        (apps_dir / "requirements.txt").write_text("requests\n")

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{apps_dir}:/apps:ro",
                "-e",
                "HASSETTE__APP_DIR=/apps",
                "-e",
                "HASSETTE__TOKEN=test_token",
                "-e",
                "HASSETTE__BASE_URL=http://test",
                "-e",
                "HASSETTE__INSTALL_DEPS=1",
                DOCKER_IMAGE,
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stderr + result.stdout

        # Only the non-empty file should be installed (1 install, not 2)
        assert output.count("Installing requirements from") == 1, f"Expected 1 install. Output:\n{output}"


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed")
def test_docker_handles_missing_requirements():
    """Test that Docker starts successfully even without requirements.txt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        # No requirements.txt file
        (apps_dir / "test_app.py").write_text("""
from hassette import App, AppConfig

class TestApp(App[AppConfig]):
    async def on_initialize(self):
        pass
""")

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{apps_dir}:/apps:ro",
                "-e",
                "HASSETTE__APP_DIR=/apps",
                "-e",
                "HASSETTE__TOKEN=test_token",
                "-e",
                "HASSETTE__BASE_URL=http://test",
                "-e",
                "HASSETTE__INSTALL_DEPS=1",
                DOCKER_IMAGE,
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Should complete successfully
        assert result.returncode == 0
        # Should show completion message even with no requirements found
        assert "Installed 0 requirements.txt file(s)" in (result.stderr + result.stdout)


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed")
def test_docker_installs_requirements_dev_variants():
    """Test that requirements-dev.txt is NOT installed (fd pattern is exact match only)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        (apps_dir / "requirements.txt").write_text("requests\n")
        (apps_dir / "requirements-dev.txt").write_text("pytest\n")

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{apps_dir}:/apps:ro",
                "-e",
                "HASSETTE__APP_DIR=/apps",
                "-e",
                "HASSETTE__TOKEN=test_token",
                "-e",
                "HASSETTE__BASE_URL=http://test",
                "-e",
                "HASSETTE__INSTALL_DEPS=1",
                DOCKER_IMAGE,
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stderr + result.stdout

        # Only requirements.txt should be installed; dev variant must be ignored
        assert output.count("Installing requirements from") == 1
        assert "requirements.txt" in output
        assert "requirements-dev.txt" not in output


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed")
def test_docker_skips_requirements_by_default():
    """Test that requirements are NOT installed when INSTALL_DEPS is unset (default-off)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()
        (apps_dir / "requirements.txt").write_text("requests\n")

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{apps_dir}:/apps:ro",
                "-e",
                "HASSETTE__APP_DIR=/apps",
                "-e",
                "HASSETTE__TOKEN=test_token",
                "-e",
                "HASSETTE__BASE_URL=http://test",
                # Intentionally omitting HASSETTE__INSTALL_DEPS
                DOCKER_IMAGE,
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stderr + result.stdout

        # Startup should succeed but requirements should be skipped
        assert result.returncode == 0
        assert "Runtime dependency installation disabled" in output
        assert "Installing requirements from" not in output


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed")
def test_docker_constraint_conflict():
    """Test that a requirements.txt conflicting with constraints fails with a clear error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        # aiohttp==3.0.0 conflicts with hassette's aiohttp>=3.9 constraint
        (apps_dir / "requirements.txt").write_text("aiohttp==3.0.0\n")

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{apps_dir}:/apps:ro",
                "-e",
                "HASSETTE__APP_DIR=/apps",
                "-e",
                "HASSETTE__TOKEN=test_token",
                "-e",
                "HASSETTE__BASE_URL=http://test",
                "-e",
                "HASSETTE__INSTALL_DEPS=1",
                DOCKER_IMAGE,
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stderr + result.stdout

        # Container must exit with non-zero code
        assert result.returncode != 0, f"Expected non-zero exit for conflict. Output:\n{output}"
        # Must display the DEPENDENCY CONFLICT banner
        assert "DEPENDENCY CONFLICT" in output, f"Expected DEPENDENCY CONFLICT banner. Output:\n{output}"
