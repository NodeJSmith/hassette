"""The startup warning for an apps directory that is missing or holds no apps."""

from pathlib import Path

from hassette.utils.app_utils import apps_dir_warning


def test_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "apps"

    assert apps_dir_warning(missing, has_apps=False, config_files=[], cwd=tmp_path) == (
        f"Apps directory {missing} does not exist"
    )


def test_directory_without_apps(tmp_path: Path) -> None:
    assert apps_dir_warning(tmp_path, has_apps=False, config_files=[], cwd=tmp_path) == (
        f"No apps found or configured in apps directory {tmp_path}"
    )


def test_directory_with_apps(tmp_path: Path) -> None:
    assert apps_dir_warning(tmp_path, has_apps=True, config_files=[], cwd=tmp_path) is None


def test_missing_directory_names_the_path_read_from_cwd(tmp_path: Path) -> None:
    """``directory = "src/myapps"`` in ./config/hassette.toml, written as if relative to the launch dir."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (tmp_path / "src" / "myapps").mkdir(parents=True)
    missing = config_dir / "src" / "myapps"

    warning = apps_dir_warning(missing, has_apps=False, config_files=[config_dir / "hassette.toml"], cwd=tmp_path)

    assert warning == (
        f"Apps directory {missing} does not exist. Did you mean {tmp_path / 'src' / 'myapps'}? A path in a "
        f"config file is relative to that file's directory, so from {config_dir} it is written ../src/myapps"
    )


def test_no_hint_when_the_cwd_reading_does_not_exist(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    missing = config_dir / "src" / "myapps"

    assert apps_dir_warning(missing, has_apps=False, config_files=[config_dir / "hassette.toml"], cwd=tmp_path) == (
        f"Apps directory {missing} does not exist"
    )
