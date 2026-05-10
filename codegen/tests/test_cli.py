"""Unit tests for the CLI entry point."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_HA_CORE = Path("~/source/core").expanduser()
_HAS_HA_CORE = _HA_CORE.exists()
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CLI = str(Path(__file__).resolve().parent.parent / "src" / "hassette_codegen" / "__main__.py")


class TestCLIBasics:
    def test_help_exits_zero(self) -> None:
        result = subprocess.run(
            ["uv", "run", "python", _CLI, "--help"],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            timeout=30,
        )
        assert result.returncode == 0
        assert "hassette-codegen" in result.stdout

    def test_no_args_exits_zero(self) -> None:
        result = subprocess.run(
            ["uv", "run", "python", _CLI],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            timeout=30,
        )
        assert result.returncode == 0

    def test_generate_requires_source(self) -> None:
        result = subprocess.run(
            ["uv", "run", "python", _CLI, "generate"],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            timeout=30,
        )
        assert result.returncode != 0

    def test_python_version_check(self) -> None:
        if not _HAS_HA_CORE:
            pytest.skip("HA core not available")
        result = subprocess.run(
            ["uv", "run", "python", _CLI, "generate", "--ha-core-path", str(_HA_CORE)],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            timeout=30,
        )
        if sys.version_info < (3, 14):  # noqa: UP036
            assert result.returncode != 0
            assert "requires Python" in result.stderr
