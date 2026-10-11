"""Unit tests for scripts/check_project_package.py."""

import importlib.metadata
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from check_project_package import find_problem


def write_pyproject(tmp_path: Path, name: str | None) -> Path:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "{name}"\n' if name else "[tool.uv]\n")
    return pyproject


def fake_distribution(*paths: str) -> SimpleNamespace:
    return SimpleNamespace(files=[importlib.metadata.PackagePath(p) for p in paths])


def test_project_without_name_is_skipped(tmp_path: Path):
    assert find_problem(write_pyproject(tmp_path, None)) is None


def test_uninstalled_distribution_is_reported(tmp_path: Path):
    problem = find_problem(write_pyproject(tmp_path, "hassette-no-such-distribution"))

    assert problem == "distribution 'hassette-no-such-distribution' is not installed"


def test_installed_distribution_with_modules_passes(tmp_path: Path):
    assert find_problem(write_pyproject(tmp_path, "pydantic")) is None


def test_distribution_with_only_metadata_and_scripts_is_reported(tmp_path: Path):
    dist = fake_distribution("test_proj-0.1.0.dist-info/RECORD", "../../../bin/test-proj")
    with patch("check_project_package.importlib.metadata.distribution", return_value=dist):
        problem = find_problem(write_pyproject(tmp_path, "test-proj"))

    assert problem == "distribution 'test-proj' contains no Python modules"


def test_distribution_with_compiled_module_only_passes(tmp_path: Path):
    dist = fake_distribution("test_proj-0.1.0.dist-info/RECORD", "test_proj.cpython-313-x86_64-linux-gnu.so")
    with patch("check_project_package.importlib.metadata.distribution", return_value=dist):
        assert find_problem(write_pyproject(tmp_path, "test-proj")) is None
