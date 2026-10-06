"""Tests for HassetteTomlConfigSettingsSource merging: [hassette] hoisting, deep merge, and the local overlay."""

import textwrap
from pathlib import Path

from pydantic import SecretStr

from hassette import HassetteConfig
from hassette.config.classes import HassetteTomlConfigSettingsSource
from hassette.testing.config import TEST_TOKEN


def make_config_cls(toml_file: Path) -> type[HassetteConfig]:
    """Return a HassetteConfig subclass whose only settings file is `toml_file` (no env files)."""

    class MinimalConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "toml_file": [toml_file],
            "env_file": [],
        }

        token: SecretStr = SecretStr(TEST_TOKEN)
        run_app_precheck: bool = False

    return MinimalConfig


def write_toml(path: Path, content: str) -> Path:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return path


class TestTomlDeepMerge:
    """Tests for deep merge behavior when [hassette.*] and top-level keys coexist."""

    def make_source(self, toml_file: Path) -> HassetteTomlConfigSettingsSource:
        return HassetteTomlConfigSettingsSource(make_config_cls(toml_file), toml_file=toml_file)

    def test_hassette_apps_and_top_level_apps_are_merged(self, tmp_path: Path) -> None:
        """Both [hassette.apps] directory settings and [apps.my_app] definitions survive."""
        toml_file = write_toml(
            tmp_path / "hassette.toml",
            """
            [hassette.apps]
            directory = "custom_apps"

            [apps.my_app]
            filename = "my_app.py"
            class_name = "MyApp"
            """,
        )
        source = self.make_source(toml_file)

        assert isinstance(source.toml_data.get("apps"), dict)
        apps = source.toml_data["apps"]
        assert apps.get("directory") == "custom_apps"
        assert isinstance(apps.get("my_app"), dict)
        assert apps["my_app"]["filename"] == "my_app.py"

    def test_hassette_section_only_unchanged(self, tmp_path: Path) -> None:
        """Only [hassette.apps] present — existing happy path works."""
        toml_file = write_toml(
            tmp_path / "hassette.toml",
            """
            [hassette.apps]
            directory = "my_apps"
            """,
        )
        source = self.make_source(toml_file)

        assert source.toml_data["apps"]["directory"] == "my_apps"

    def test_top_level_only_no_hassette_section(self, tmp_path: Path) -> None:
        """No [hassette] section — standard path, no merge logic triggered."""
        toml_file = write_toml(
            tmp_path / "hassette.toml",
            """
            [apps]
            directory = "plain_apps"
            """,
        )
        source = self.make_source(toml_file)

        assert source.toml_data["apps"]["directory"] == "plain_apps"

    def test_deep_merge_non_apps_nested_key(self, tmp_path: Path) -> None:
        """Non-apps nested keys also deep-merge rather than overwrite."""
        toml_file = write_toml(
            tmp_path / "hassette.toml",
            """
            [database]
            retention_days = 30

            [hassette.database]
            batch_size = 500
            """,
        )
        source = self.make_source(toml_file)

        db = source.toml_data["database"]
        assert db["retention_days"] == 30
        assert db["batch_size"] == 500


class TestLocalTomlOverlay:
    """hassette.local.toml is deep-merged over hassette.toml with higher priority."""

    def test_local_overrides_base_and_deep_merges(self, tmp_path: Path) -> None:
        base = write_toml(
            tmp_path / "hassette.toml",
            """
            [hassette]
            base_url = "http://shared:8123"

            [hassette.database]
            retention_days = 30
            batch_size = 100
            """,
        )
        write_toml(
            tmp_path / "hassette.local.toml",
            """
            [hassette]
            base_url = "http://localhost:8123"

            [hassette.database]
            batch_size = 500
            """,
        )

        source = HassetteTomlConfigSettingsSource(make_config_cls(base), toml_file=base)

        assert source.toml_data["base_url"] == "http://localhost:8123"
        assert source.toml_data["database"] == {"retention_days": 30, "batch_size": 500}

    def test_local_top_level_key_overrides_base_hassette_section(self, tmp_path: Path) -> None:
        """Each file's [hassette] section is hoisted before merging, so section style doesn't matter."""
        base = write_toml(tmp_path / "hassette.toml", '[hassette]\nbase_url = "http://shared:8123"\n')
        write_toml(tmp_path / "hassette.local.toml", 'base_url = "http://localhost:8123"\n')

        source = HassetteTomlConfigSettingsSource(make_config_cls(base), toml_file=base)

        assert source.toml_data["base_url"] == "http://localhost:8123"

    def test_later_base_file_replaces_earlier_table_across_section_styles(self, tmp_path: Path) -> None:
        """Base files are hoisted one at a time, so a later `[apps]` replaces an earlier `[hassette.apps]`."""
        first = write_toml(
            tmp_path / "first.toml",
            """
            [hassette.apps.old_app]
            filename = "old_app.py"
            class_name = "OldApp"
            """,
        )
        second = write_toml(
            tmp_path / "second.toml",
            """
            [apps.new_app]
            filename = "new_app.py"
            class_name = "NewApp"
            """,
        )

        source = HassetteTomlConfigSettingsSource(make_config_cls(first), toml_file=[first, second])

        assert set(source.toml_data["apps"]) == {"new_app"}

    def test_local_overlay_adds_app_config(self, tmp_path: Path) -> None:
        base = write_toml(
            tmp_path / "hassette.toml",
            """
            [apps.my_app]
            filename = "my_app.py"
            class_name = "MyApp"
            config = {threshold = 5}
            """,
        )
        write_toml(tmp_path / "hassette.local.toml", '[apps.my_app.config]\napi_key = "secret"\n')

        source = HassetteTomlConfigSettingsSource(make_config_cls(base), toml_file=base)

        assert source.toml_data["apps"]["my_app"]["config"] == {"threshold": 5, "api_key": "secret"}
        assert source.toml_data["apps"]["my_app"]["filename"] == "my_app.py"

    def test_overlay_without_base_file_is_loaded(self, tmp_path: Path) -> None:
        base = tmp_path / "hassette.toml"
        write_toml(tmp_path / "hassette.local.toml", 'base_url = "http://localhost:8123"\n')

        source = HassetteTomlConfigSettingsSource(make_config_cls(base), toml_file=base)

        assert source.toml_data["base_url"] == "http://localhost:8123"

    def test_overlay_follows_custom_config_file_name(self, tmp_path: Path) -> None:
        base = write_toml(tmp_path / "prod.toml", 'base_url = "http://shared:8123"\n')
        write_toml(tmp_path / "prod.local.toml", 'base_url = "http://localhost:8123"\n')

        source = HassetteTomlConfigSettingsSource(make_config_cls(base), toml_file=str(base))

        assert source.toml_data["base_url"] == "http://localhost:8123"

    def test_config_loads_overlay(self, tmp_path: Path) -> None:
        base = write_toml(tmp_path / "hassette.toml", '[hassette]\nbase_url = "http://shared:8123"\n')
        write_toml(tmp_path / "hassette.local.toml", '[hassette]\nbase_url = "http://localhost:8123"\n')

        config = make_config_cls(base)()

        assert config.base_url == "http://localhost:8123"

    def test_config_toml_files_include_existing_overlay(self, tmp_path: Path) -> None:
        base = write_toml(tmp_path / "hassette.toml", '[hassette]\nbase_url = "http://shared:8123"\n')
        local = write_toml(tmp_path / "hassette.local.toml", '[hassette]\nbase_url = "http://localhost:8123"\n')

        config = make_config_cls(base)()

        assert config.toml_files == {base.resolve(), local.resolve()}
