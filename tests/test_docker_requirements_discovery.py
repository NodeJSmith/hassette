"""Tests for Docker requirements.txt discovery using fd command.

These tests verify that the fd command pattern used in docker_start.sh
correctly finds user's requirements.txt files in mounted volumes.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

fd_path = shutil.which("fd") or shutil.which("fdfind")


@pytest.mark.skipif(fd_path is None, reason="fd command not found")
def test_fd_finds_requirements_txt():
    """Test that fd command finds requirements.txt files as expected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create test structure
        (tmp_path / "app1").mkdir()
        (tmp_path / "app1" / "requirements.txt").write_text("requests==2.31.0\n")

        (tmp_path / "app2" / "subdir").mkdir(parents=True)
        (tmp_path / "app2" / "subdir" / "requirements.txt").write_text("aiohttp==3.9.0\n")

        # This should NOT be found (wrong extension)
        (tmp_path / "requirements.md").write_text("# Not a requirements file\n")

        # Run the fd command (matching docker_start.sh logic)
        result = subprocess.run(
            [fd_path, "-t", "f", "-a", "-0", "requirements", "--extension", "txt", str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )

        # Split by null terminator and filter empty strings
        found_files = [f for f in result.stdout.split("\0") if f]

        assert len(found_files) == 2, f"Expected 2 files, found {len(found_files)}: {found_files}"
        assert any("app1/requirements.txt" in f for f in found_files)
        assert any("app2/subdir/requirements.txt" in f for f in found_files)


@pytest.mark.skipif(fd_path is None, reason="fd command not found")
def test_fd_finds_requirements_in_config_and_apps():
    """Test fd finds requirements in both CONFIG and APP_DIR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Simulate /config and /apps directories
        config_dir = tmp_path / "config"
        apps_dir = tmp_path / "apps"
        config_dir.mkdir()
        apps_dir.mkdir()

        (config_dir / "requirements.txt").write_text("pyyaml==6.0\n")
        (apps_dir / "requirements.txt").write_text("httpx==0.25.0\n")

        # Run fd on both roots (space-separated like in script)
        result = subprocess.run(
            [
                fd_path,
                "-t",
                "f",
                "-a",
                "-0",
                "requirements",
                "--extension",
                "txt",
                str(config_dir),
                str(apps_dir),
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        found_files = [f for f in result.stdout.split("\0") if f]

        assert len(found_files) == 2
        assert any("config/requirements.txt" in f for f in found_files)
        assert any("apps/requirements.txt" in f for f in found_files)


@pytest.mark.skipif(fd_path is None, reason="fd command not found")
def test_fd_ignores_hidden_files():
    """Test that fd ignores .git, .venv, etc by default."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create requirements in .venv (should be ignored)
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "requirements.txt").write_text("ignored\n")

        # Create requirements in normal location (should be found)
        (tmp_path / "requirements.txt").write_text("found\n")

        result = subprocess.run(
            [fd_path, "-t", "f", "-a", "-0", "requirements", "--extension", "txt", str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )

        found_files = [f for f in result.stdout.split("\0") if f]

        # Should only find the one NOT in .venv
        assert len(found_files) == 1
        assert ".venv" not in found_files[0]


@pytest.mark.skipif(fd_path is None, reason="fd command not found")
def test_empty_requirements_files_skipped():
    """Test that empty requirements.txt files are skipped (script checks with -s)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Empty file
        (tmp_path / "empty_requirements.txt").touch()

        # Non-empty file
        (tmp_path / "requirements.txt").write_text("requests\n")

        result = subprocess.run(
            [fd_path, "-t", "f", "-a", "-0", "requirements", "--extension", "txt", str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )

        found_files = [f for f in result.stdout.split("\0") if f]

        # Both should be found by fd, but script filters empty ones with [ -s "$req" ]
        assert len(found_files) == 2

        # Simulate the script's [ -s "$req" ] check
        non_empty = [f for f in found_files if Path(f).stat().st_size > 0]
        assert len(non_empty) == 1
        assert "empty_requirements.txt" not in non_empty[0]


@pytest.mark.skipif(fd_path is None, reason="fd command not found")
def test_fd_handles_multiple_requirements_patterns():
    """Test that files like requirements-dev.txt are also found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create various requirements file patterns
        (tmp_path / "requirements.txt").write_text("base\n")
        (tmp_path / "requirements-dev.txt").write_text("dev\n")
        (tmp_path / "requirements_test.txt").write_text("test\n")

        result = subprocess.run(
            [fd_path, "-t", "f", "-a", "-0", "requirements", "--extension", "txt", str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )

        found_files = [f for f in result.stdout.split("\0") if f]

        # All should be found - fd pattern 'requirements' matches any file containing that string
        assert len(found_files) == 3
        assert any("requirements.txt" in f for f in found_files)
        assert any("requirements-dev.txt" in f for f in found_files)
        assert any("requirements_test.txt" in f for f in found_files)
