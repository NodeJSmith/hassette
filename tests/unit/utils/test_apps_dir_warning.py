"""The startup warning for an apps directory that is missing or holds no apps."""

from pathlib import Path

from hassette.utils.app_utils import apps_dir_warning


def test_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "apps"

    assert apps_dir_warning(missing, has_apps=False) == f"Apps directory {missing} does not exist"


def test_directory_without_apps(tmp_path: Path) -> None:
    assert apps_dir_warning(tmp_path, has_apps=False) == f"No apps found or configured in apps directory {tmp_path}"


def test_directory_with_apps(tmp_path: Path) -> None:
    assert apps_dir_warning(tmp_path, has_apps=True) is None
