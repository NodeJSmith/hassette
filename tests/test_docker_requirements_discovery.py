"""Tests for Docker requirements.txt discovery using fd command.

These tests verify that the fd command pattern used in docker_start.sh
correctly finds user's requirements.txt files in mounted volumes.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

fd_path = shutil.which("fd") or shutil.which("fdfind")


def find_requirements(*search_dirs: str | Path) -> list[str]:
    """Run fd to discover requirements.txt files, matching docker_start.sh's exact-match pattern."""
    result = subprocess.run(
        [fd_path, "-t", "f", "-a", "-0", "--max-depth", "5", "^requirements\\.txt$", *(str(d) for d in search_dirs)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [f for f in result.stdout.split("\0") if f]


@pytest.mark.skipif(fd_path is None, reason="fd command not found")
def test_fd_finds_requirements_txt(tmp_path: Path):
    """Test that fd command finds requirements.txt files as expected."""
    (tmp_path / "app1").mkdir()
    (tmp_path / "app1" / "requirements.txt").write_text("requests>=2.28\n")

    (tmp_path / "app2" / "subdir").mkdir(parents=True)
    (tmp_path / "app2" / "subdir" / "requirements.txt").write_text("aiohttp>=3.9\n")

    # This should NOT be found (wrong extension)
    (tmp_path / "requirements.md").write_text("# Not a requirements file\n")

    found_files = find_requirements(tmp_path)

    assert len(found_files) == 2, f"Expected 2 files, found {len(found_files)}: {found_files}"
    assert any("app1/requirements.txt" in f for f in found_files)
    assert any("app2/subdir/requirements.txt" in f for f in found_files)


@pytest.mark.skipif(fd_path is None, reason="fd command not found")
def test_fd_finds_requirements_in_config_and_apps(tmp_path: Path):
    """Test fd finds requirements in both CONFIG and APP_DIR."""
    config_dir = tmp_path / "config"
    apps_dir = tmp_path / "apps"
    config_dir.mkdir()
    apps_dir.mkdir()

    (config_dir / "requirements.txt").write_text("pyyaml>=6.0\n")
    (apps_dir / "requirements.txt").write_text("httpx>=0.25\n")

    found_files = find_requirements(config_dir, apps_dir)

    assert len(found_files) == 2
    assert any("config/requirements.txt" in f for f in found_files)
    assert any("apps/requirements.txt" in f for f in found_files)


@pytest.mark.skipif(fd_path is None, reason="fd command not found")
def test_fd_ignores_hidden_files(tmp_path: Path):
    """Test that fd ignores .git, .venv, etc by default."""
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "requirements.txt").write_text("ignored\n")

    (tmp_path / "requirements.txt").write_text("found\n")

    found_files = find_requirements(tmp_path)

    assert len(found_files) == 1
    assert ".venv" not in found_files[0]


@pytest.mark.skipif(fd_path is None, reason="fd command not found")
def test_empty_requirements_files_skipped(tmp_path: Path):
    """Test that empty requirements.txt files are skipped (script checks with -s)."""
    # Empty file — exact match pattern finds it, but script skips it
    (tmp_path / "requirements.txt").touch()

    # Non-empty file in a subdir
    (tmp_path / "subapp").mkdir()
    (tmp_path / "subapp" / "requirements.txt").write_text("requests\n")

    found_files = find_requirements(tmp_path)

    # Both should be found by fd, but script filters empty ones with [ -s "$req" ]
    assert len(found_files) == 2

    # Simulate the script's [ -s "$req" ] check
    non_empty = [f for f in found_files if Path(f).stat().st_size > 0]
    assert len(non_empty) == 1
    assert "subapp/requirements.txt" in non_empty[0]


@pytest.mark.skipif(fd_path is None, reason="fd command not found")
def test_fd_handles_multiple_requirements_patterns(tmp_path: Path):
    """Test that only requirements.txt is found; dev/test variants are excluded by exact-match pattern."""
    (tmp_path / "requirements.txt").write_text("base\n")
    (tmp_path / "requirements-dev.txt").write_text("dev\n")
    (tmp_path / "requirements_test.txt").write_text("test\n")

    found_files = find_requirements(tmp_path)

    # Only the exact requirements.txt should be found — dev/test variants are excluded
    assert len(found_files) == 1, f"Expected 1 file, found {len(found_files)}: {found_files}"
    assert any("requirements.txt" in f and "requirements-dev.txt" not in f for f in found_files)
    assert not any("requirements-dev.txt" in f for f in found_files)
    assert not any("requirements_test.txt" in f for f in found_files)
