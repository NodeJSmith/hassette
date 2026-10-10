"""Where config files are looked up, and what relative paths and ``apps.directory`` resolve to."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import BaseModel

from hassette import HassetteConfig
from hassette.config import locations
from hassette.config.classes import AppManifest, is_path_annotation, model_annotation
from hassette.config.helpers import get_log_level
from hassette.config.locations import resolve_locations
from hassette.config.models import AppsConfig


@pytest.fixture
def no_docker_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the unset-config_dir default at a temp dir standing in for platformdirs."""
    default_dir = tmp_path / "platform-config"
    monkeypatch.setattr(locations, "DOCKER_CONFIG_DIR", tmp_path / "no-such-config")
    monkeypatch.setattr(locations.platformdirs, "user_config_path", lambda *_a, **_kw: default_dir)
    return default_dir


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestResolveLocations:
    def test_explicit_config_dir_is_the_only_search_dir(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg"
        result = resolve_locations({"HASSETTE__CONFIG_DIR": str(cfg)}, cwd=tmp_path)

        assert result.config_dir_explicit
        assert result.toml_files == (cfg / "hassette.toml",)
        assert result.env_files == (cfg / ".env",)
        assert result.config_home == cfg

    @pytest.mark.parametrize("name", ["HASSETTE__CONFIG_DIR", "hassette__config_dir", "HASSETTE_CONFIG_DIR"])
    def test_config_dir_env_names_match_case_insensitively(self, tmp_path: Path, name: str) -> None:
        result = resolve_locations({name: str(tmp_path / "cfg")}, cwd=tmp_path)

        assert result.config_dir == tmp_path / "cfg"

    def test_config_dir_argument_beats_env(self, tmp_path: Path) -> None:
        result = resolve_locations({"HASSETTE__CONFIG_DIR": "/env"}, config_dir="flag", cwd=tmp_path)

        assert result.config_dir == tmp_path / "flag"

    def test_unset_config_dir_searches_default_then_cwd_then_config_subdir(
        self, tmp_path: Path, no_docker_config_dir: Path
    ) -> None:
        result = resolve_locations({}, cwd=tmp_path)

        assert not result.config_dir_explicit
        assert result.config_dir == no_docker_config_dir
        assert result.toml_files == (
            no_docker_config_dir / "hassette.toml",
            tmp_path / "hassette.toml",
            tmp_path / "config" / "hassette.toml",
        )
        assert result.config_home == tmp_path

    def test_existing_docker_config_dir_is_the_config_home_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty HASSETTE__CONFIG_DIR in Docker must not anchor apps at the image's own /app."""
        docker_config = tmp_path / "config-volume"
        docker_config.mkdir()
        monkeypatch.setattr(locations, "DOCKER_CONFIG_DIR", docker_config)

        result = resolve_locations({"HASSETTE__CONFIG_DIR": ""}, cwd=tmp_path / "app")

        assert not result.config_dir_explicit
        assert result.config_dir == docker_config
        assert result.config_home == docker_config

    def test_file_flags_replace_the_search_lists(self, tmp_path: Path) -> None:
        result = resolve_locations(
            {"HASSETTE__CONFIG_DIR": "/cfg"}, config_file="my.toml", env_file="my.env", cwd=tmp_path
        )

        assert result.toml_files == (tmp_path / "my.toml",)
        assert result.env_files == (tmp_path / "my.env",)


class TestConfigDirLookup:
    def test_explicit_config_dir_ignores_a_cwd_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """#2626: the file in config_dir is read, and a stray one in cwd is not."""
        cfg = tmp_path / "cfg"
        write(cfg / "hassette.toml", 'base_url = "http://from-config-dir:8123"\n')
        write(tmp_path / "hassette.toml", 'base_url = "http://from-cwd:8123"\n')
        monkeypatch.chdir(tmp_path)

        config = HassetteConfig(environ={"HASSETTE__CONFIG_DIR": str(cfg)})

        assert config.base_url == "http://from-config-dir:8123"
        assert config.config_dir == cfg

    def test_unset_config_dir_still_reads_cwd_config_subdir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_docker_config_dir: Path
    ) -> None:
        write(tmp_path / "config" / "hassette.toml", 'base_url = "http://from-subdir:8123"\n')
        monkeypatch.chdir(tmp_path)

        config = HassetteConfig(environ={})

        assert config.base_url == "http://from-subdir:8123"
        assert config.config_dir == no_docker_config_dir


class TestRelativePaths:
    def test_toml_paths_are_relative_to_the_toml_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "cfg"
        write(
            cfg / "hassette.toml",
            'data_dir = "data"\n[apps]\ndirectory = "my_apps"\n[database]\npath = "db/h.db"\n'
            '[cli]\ntoken_file = "token"\n[apps.my_app]\nfilename = "a.py"\nclass_name = "A"\napp_dir = "sub"\n',
        )
        monkeypatch.chdir(tmp_path)

        config = config_from_dir(cfg)

        assert config.data_dir == cfg / "data"
        assert config.apps.directory == cfg / "my_apps"
        assert config.database.path == cfg / "db" / "h.db"
        assert config.cli.token_file == cfg / "token"
        assert config.apps.apps["my_app"]["app_dir"] == cfg / "sub"

    def test_empty_toml_path_is_unset_not_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``""`` falls back to the default, as an empty env var does, instead of becoming ``Path(".")``."""
        cfg = tmp_path / "cfg"
        write(
            cfg / "hassette.toml",
            '[apps]\ndirectory = ""\n[apps.my_app]\nfilename = "a.py"\nclass_name = "A"\napp_dir = ""\n',
        )
        monkeypatch.chdir(tmp_path)

        config = config_from_dir(cfg)

        assert config.apps.directory == cfg / "apps"
        assert "app_dir" not in config.apps.apps["my_app"]

    def test_symlinked_config_file_anchors_at_the_link(self, tmp_path: Path) -> None:
        link = symlinked_config_dir(tmp_path)

        config = HassetteConfig(environ={}, config_file=link / "hassette.toml", env_file=[], strict_inputs=False)

        assert config.apps.directory == link / "apps"

    def test_symlinked_config_dir_anchors_at_the_link(self, tmp_path: Path) -> None:
        link = symlinked_config_dir(tmp_path)

        config = config_from_dir(link)

        assert config.apps.directory == link / "apps"

    def test_every_path_field_shape_is_anchored(self) -> None:
        """A path-bearing field `anchor_paths` can't anchor (e.g. ``list[Path]``) would stay cwd-relative."""
        unsupported = [
            name
            for name, annotation in walk_annotations(HassetteConfig)
            if mentions_path(annotation) and not is_path_annotation(annotation)
        ]

        assert unsupported == []

    def test_parent_segments_are_collapsed(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg"
        write(cfg / "hassette.toml", '[apps]\ndirectory = "../apps"\n')

        config = config_from_dir(cfg)

        assert config.apps.directory == tmp_path / "apps"
        assert ".." not in config.apps.directory.parts

    def test_local_overlay_paths_are_relative_to_the_overlay(self, tmp_path: Path) -> None:
        base = write(tmp_path / "base" / "hassette.toml", '[apps]\ndirectory = "from_base"\n')
        write(tmp_path / "base" / "hassette.local.toml", '[apps]\ndirectory = "from_overlay"\n')

        config = HassetteConfig(environ={}, config_file=base, env_file=[])

        assert config.apps.directory == tmp_path / "base" / "from_overlay"

    def test_env_file_paths_are_relative_to_the_env_file(self, tmp_path: Path) -> None:
        env = write(tmp_path / "cfg" / ".env", "HASSETTE__DATA_DIR=data\n")

        config = HassetteConfig(environ={}, config_file=[], env_file=env)

        assert config.data_dir == tmp_path / "cfg" / "data"

    def test_process_env_and_init_paths_are_relative_to_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        config = HassetteConfig(
            environ={"HASSETTE__DATA_DIR": "data"}, config_file=[], env_file=[], database={"path": "h.db"}
        )

        assert config.data_dir == tmp_path / "data"
        assert config.database.path == tmp_path / "h.db"

    @pytest.mark.parametrize("name", ["HASSETTE_DATA_DIR", "HASSETTE__DATA_DIR"])
    def test_env_data_dir_alias_is_relative_to_the_supplied_cwd(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, name: str
    ) -> None:
        """A relative data-dir env value anchors to the build's cwd, not the process cwd."""
        monkeypatch.chdir(tmp_path_factory.mktemp("elsewhere"))

        config = HassetteConfig(environ={name: "data"}, cwd=tmp_path, config_file=[], env_file=[])

        assert config.data_dir == tmp_path / "data"


class TestAppsDirectoryDefault:
    def test_defaults_to_apps_in_explicit_config_dir(self, tmp_path: Path) -> None:
        (tmp_path / "cfg").mkdir()
        config = HassetteConfig(environ={"HASSETTE__CONFIG_DIR": str(tmp_path / "cfg")})

        assert config.apps.directory == tmp_path / "cfg" / "apps"

    def test_defaults_to_cwd_apps_without_explicit_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_docker_config_dir: Path
    ) -> None:
        write(tmp_path / "config" / "hassette.toml", 'base_url = "http://ha:8123"\n')
        monkeypatch.chdir(tmp_path)

        config = HassetteConfig(environ={})

        assert config.apps.directory == tmp_path / "apps"


class TestBootstrapLogLevel:
    def test_reads_the_logging_setting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HASSETTE__LOGGING__LOG_LEVEL", "debug")

        assert get_log_level() == "DEBUG"

    def test_ignores_the_retired_flat_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("HASSETTE__LOGGING__LOG_LEVEL", "HASSETTE_LOG_LEVEL", "LOG_LEVEL"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("HASSETTE__LOG_LEVEL", "DEBUG")

        assert get_log_level() == "INFO"


def config_from_dir(config_dir: Path) -> HassetteConfig:
    """Load the config whose ``HASSETTE__CONFIG_DIR`` is `config_dir`, without the unknown-key checks."""
    return HassetteConfig(environ={"HASSETTE__CONFIG_DIR": str(config_dir)}, strict_inputs=False)


def symlinked_config_dir(tmp_path: Path) -> Path:
    """Write ``real/hassette.toml`` setting a relative apps directory; return a symlink ``link`` -> ``real``."""
    write(tmp_path / "real" / "hassette.toml", '[apps]\ndirectory = "apps"\n')
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    return link


def walk_annotations(model: type[BaseModel], prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Yield each field's dotted name and annotation, descending into nested models.

    App definitions under ``apps`` are walked as `AppManifest`, mirroring how `anchor_paths` treats them.
    """
    for name, info in model.model_fields.items():
        yield f"{prefix}{name}", info.annotation
        if (sub := model_annotation(info.annotation)) is not None:
            yield from walk_annotations(sub, f"{prefix}{name}.")
    if model is AppsConfig:
        yield from walk_annotations(AppManifest, f"{prefix}<app>.")


def mentions_path(annotation: Any) -> bool:
    """True when ``Path`` appears anywhere in `annotation` (``list[Path]`` too), unlike `is_path_annotation`,
    which accepts only the shapes `anchor_paths` anchors (``Path``, ``Path | None``).
    """
    return annotation is Path or any(mentions_path(arg) for arg in get_args(annotation))
