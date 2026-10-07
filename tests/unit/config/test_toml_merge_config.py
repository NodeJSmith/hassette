"""Tests for HassetteTomlConfigSettingsSource merging: [hassette] hoisting, deep merge, and the local overlay."""

import textwrap
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from hassette import HassetteConfig
from hassette.config.classes import HassetteTomlConfigSettingsSource
from hassette.testing.config import TEST_TOKEN


def make_config_cls(toml_file: Path) -> type[HassetteConfig]:
    """Return a HassetteConfig subclass whose only settings file is `toml_file` (no env files)."""

    class MinimalConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | SettingsConfigDict(
            cli_parse_args=False, toml_file=[toml_file], env_file=[]
        )

        token: SecretStr = SecretStr(TEST_TOKEN)
        run_app_precheck: bool = False

    return MinimalConfig


def make_source(toml_file: Path) -> HassetteTomlConfigSettingsSource:
    return HassetteTomlConfigSettingsSource(make_config_cls(toml_file), toml_file=toml_file)


def write_toml(path: Path, content: str) -> Path:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return path


class TestTomlDeepMerge:
    """Tests for deep merge behavior when [hassette.*] and top-level keys coexist."""

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
        source = make_source(toml_file)

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
        source = make_source(toml_file)

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
        source = make_source(toml_file)

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
        source = make_source(toml_file)

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

        source = make_source(base)

        assert source.toml_data["base_url"] == "http://localhost:8123"
        assert source.toml_data["database"] == {"retention_days": 30, "batch_size": 500}

    def test_local_top_level_key_overrides_base_hassette_section(self, tmp_path: Path) -> None:
        """Each file's [hassette] section is hoisted before merging, so section style doesn't matter."""
        base = write_toml(tmp_path / "hassette.toml", '[hassette]\nbase_url = "http://shared:8123"\n')
        write_toml(tmp_path / "hassette.local.toml", 'base_url = "http://localhost:8123"\n')

        source = make_source(base)

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

        source = make_source(base)

        assert source.toml_data["apps"]["my_app"]["config"] == {"threshold": 5, "api_key": "secret"}
        assert source.toml_data["apps"]["my_app"]["filename"] == "my_app.py"

    def test_overlay_without_base_file_is_loaded(self, tmp_path: Path) -> None:
        base = tmp_path / "hassette.toml"
        write_toml(tmp_path / "hassette.local.toml", 'base_url = "http://localhost:8123"\n')

        source = make_source(base)

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


def make_aliased_config_cls(files: list[Path]) -> type[HassetteConfig]:
    """Like `make_config_cls`, but keeps HassetteConfig's own `token` field and its aliases."""

    class AliasedConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | SettingsConfigDict(
            cli_parse_args=False, toml_file=files, env_file=[]
        )

        run_app_precheck: bool = False

    return AliasedConfig


class TestAliasCanonicalization:
    """Each file's alias spellings are canonicalized before layers merge, so the later layer wins."""

    def test_overlay_alias_overrides_base_field_name(self, tmp_path: Path) -> None:
        base = write_toml(tmp_path / "hassette.toml", 'token = "BASE"\n')
        write_toml(tmp_path / "hassette.local.toml", 'ha_token = "LOCAL"\n')

        config = make_aliased_config_cls([base])()

        assert config.token is not None
        assert config.token.get_secret_value() == "LOCAL"

    def test_overlay_app_config_alias_overrides_base_config(self, tmp_path: Path) -> None:
        base = write_toml(
            tmp_path / "hassette.toml",
            """
            [apps.my_app]
            filename = "my_app.py"
            class_name = "MyApp"
            config = {a = 1}
            """,
        )
        write_toml(tmp_path / "hassette.local.toml", "[apps.my_app]\napp_config = {a = 2}\n")

        source = HassetteTomlConfigSettingsSource(make_aliased_config_cls([base]), toml_file=base)

        entry = source.toml_data["apps"]["my_app"]
        assert entry["config"] == {"a": 2}
        assert "app_config" not in entry

    def test_later_base_file_alias_wins(self, tmp_path: Path) -> None:
        first = write_toml(tmp_path / "first.toml", 'token = "FIRST"\n')
        second = write_toml(tmp_path / "second.toml", 'ha_token = "SECOND"\n')

        config = make_aliased_config_cls([first, second])()

        assert config.token is not None
        assert config.token.get_secret_value() == "SECOND"

    def test_hassette_section_alias_beats_top_level_spelling(self, tmp_path: Path) -> None:
        toml_file = write_toml(tmp_path / "hassette.toml", 'token = "TOP"\n[hassette]\nha_token = "SECTION"\n')

        config = make_aliased_config_cls([toml_file])()

        assert config.token is not None
        assert config.token.get_secret_value() == "SECTION"

    def test_both_spellings_in_one_table_follow_alias_order(self, tmp_path: Path) -> None:
        """When one table has several spellings, the first in the field's alias order is kept."""
        toml_file = write_toml(tmp_path / "hassette.toml", 'ha_token = "ALIAS"\ntoken = "CANONICAL"\n')

        source = HassetteTomlConfigSettingsSource(make_aliased_config_cls([toml_file]), toml_file=toml_file)

        assert source.toml_data["token"] == "CANONICAL"
        assert "ha_token" not in source.toml_data

    def test_hassette_apps_section_entries_are_canonicalized(self, tmp_path: Path) -> None:
        base = write_toml(
            tmp_path / "hassette.toml",
            """
            [hassette.apps.my_app]
            file_name = "my_app.py"
            class = "MyApp"
            app_config = {a = 1}
            """,
        )

        source = HassetteTomlConfigSettingsSource(make_aliased_config_cls([base]), toml_file=base)

        assert source.toml_data["apps"]["my_app"] == {
            "filename": "my_app.py",
            "class_name": "MyApp",
            "config": {"a": 1},
        }
