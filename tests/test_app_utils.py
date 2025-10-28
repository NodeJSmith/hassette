from pathlib import Path
from textwrap import dedent

import pytest

from hassette.utils.app_utils import _module_name_for


def test_module_name_for_with_invalid_path(tmp_path: Path):
    """Test _module_name_for with an invalid path."""

    app_file = tmp_path / "non_existent.py"

    with pytest.raises(FileNotFoundError):
        _module_name_for(tmp_path, app_file, "")


def test_module_name_for_with_directory_path(tmp_path: Path):
    """Test _module_name_for with a directory path."""

    app_dir = tmp_path / "app_dir"
    app_dir.mkdir()

    with pytest.raises(IsADirectoryError):
        _module_name_for(tmp_path, app_dir, "")


def test_module_name_for_with_no_parent(tmp_path: Path):
    """Test _module_name_for when there is no parent package."""

    app_file = tmp_path / "test.py"
    app_file.write_text(
        dedent("""
        from hassette import App, AppConfig

        class CurrentDirApp(App[AppConfig]): ...
    """)
    )

    module_name = _module_name_for(tmp_path, app_file, "")
    assert module_name == "test", f"Expected 'test', got '{module_name}'"


def test_module_name_for_with_parent(tmp_path: Path):
    """Test _module_name_for when there is a parent package."""

    app_path = tmp_path / "apps"
    app_path.mkdir()
    app_file = app_path / "test.py"
    app_file.write_text(
        dedent("""
        from hassette import App, AppConfig

        class CurrentDirApp(App[AppConfig]): ...
    """)
    )

    module_name = _module_name_for(tmp_path, app_file, "")
    assert module_name == "apps.test", f"Expected 'apps.test', got '{module_name}'"
