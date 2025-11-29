from pathlib import Path

import dotenv

from hassette import HassetteConfig
from hassette.config.defaults import AUTODETECT_EXCLUDE_DIRS_DEFAULT


def test_overrides_are_used(env_file_path: Path, test_config: HassetteConfig) -> None:
    """Configuration values honour overrides from the test TOML and .env."""

    test_config.reload()

    expected_value = dotenv.get_key(env_file_path, "hassette__apps_log_level")

    assert test_config.apps_log_level == expected_value, (
        f"Expected apps_log_level to be {expected_value}, got {test_config.apps_log_level}"
    )


def test_env_overrides_are_used(test_config_class, monkeypatch, tmp_path):
    """Environment overrides win when constructing a HassetteConfig."""
    app_dir = tmp_path / "custom/apps"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("hassette__app_dir", str(app_dir))
    config_with_env_override = test_config_class()
    assert config_with_env_override.app_dir == app_dir, f"Expected {app_dir}, got {config_with_env_override.app_dir}"


def test_extended_autodetect_exclude_dirs(test_config_class):
    """Test that extended autodetect_exclude_dirs are handled correctly."""

    config_with_extended_excludes = test_config_class(extend_autodetect_exclude_dirs=[".hg", ".svn", "custom_dir"])
    expected_excludes = set(AUTODETECT_EXCLUDE_DIRS_DEFAULT) | {".hg", ".svn", "custom_dir"}
    assert set(config_with_extended_excludes.autodetect_exclude_dirs) == expected_excludes, (
        f"Expected {expected_excludes}, got {set(config_with_extended_excludes.autodetect_exclude_dirs)}"
    )
