"""Explicit locations that don't exist, keys that match no setting, ``config_dir`` set in a file, and reloads."""

from pathlib import Path

import pytest

from hassette import HassetteConfig
from hassette.config.checks import CONFIG_REFERENCE_URL
from hassette.exceptions import ConfigError

DOCS_DIR = Path(__file__).parents[3] / "docs"
DOCS_SITE_VERSION_ROOT = "https://hassette.readthedocs.io/en/stable/"


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    path = tmp_path / "cfg"
    path.mkdir()
    return path


def load(cfg: Path, *, toml: str = "", dotenv: str = "", env: dict[str, str] | None = None) -> HassetteConfig:
    (cfg / "hassette.toml").write_text(toml, encoding="utf-8")
    (cfg / ".env").write_text(dotenv, encoding="utf-8")
    return HassetteConfig(environ={"HASSETTE__CONFIG_DIR": str(cfg), **(env or {})})


def unknown_error(cfg: Path, **kwargs: str | dict[str, str]) -> str:
    with pytest.raises(ConfigError) as exc_info:
        load(cfg, **kwargs)  # pyright: ignore[reportArgumentType]
    return str(exc_info.value)


class TestFlagged:
    @pytest.mark.parametrize(
        "name",
        [
            pytest.param("HASSETTE__APP_DIR", id="retired-docker-apps-var"),
            pytest.param("HASSETTE__APPS__DIRECTRY", id="nested-typo"),
            pytest.param("HASSETTE__LOG_LEVEL", id="retired-flat-log-level"),
            pytest.param("HASSETTE__INSTALL_DEPS", id="retired-docker-script-var"),
            pytest.param("HASSETTE__HA_TOKEN", id="unprefixed-alias-with-prefix"),
            pytest.param("HASSETTE__APPS__MY_APP", id="scalar-app-key"),
            pytest.param("HASSETTE__MYAPP_SETTING", id="app-prefix-inside-reserved-namespace"),
        ],
    )
    def test_process_env_var(self, cfg: Path, name: str) -> None:
        message = unknown_error(cfg, env={name: "1"})

        assert f"{name} (from environment)" in message
        assert "reserved for Hassette settings" in message

    @pytest.mark.parametrize("name", ["HASSETTE__DOTENV_TYPO", "hassette__dotenv_typo"])
    def test_dotenv_var_any_case(self, cfg: Path, name: str) -> None:
        message = unknown_error(cfg, dotenv=f"{name}=1\n")

        assert f"{name} (from {cfg / '.env'})" in message

    @pytest.mark.parametrize(
        ("toml", "dotted"),
        [
            pytest.param("bogus = 1\n", "bogus", id="top-level"),
            pytest.param("[hassette]\nbogus = 1\n", "bogus", id="hoisted"),
            pytest.param("[hassette.apps]\ndirectry = 'x'\n", "apps.directry", id="nested"),
            pytest.param("[logging]\nlevle = 'INFO'\n", "logging.levle", id="nested-group"),
            pytest.param("[tool.other]\nx = 1\n", "tool", id="foreign-table"),
        ],
    )
    def test_toml_key(self, cfg: Path, toml: str, dotted: str) -> None:
        message = unknown_error(cfg, toml=toml)

        assert f"{dotted} (from {cfg / 'hassette.toml'})" in message

    def test_every_unknown_key_listed_once(self, cfg: Path) -> None:
        message = unknown_error(
            cfg,
            toml="bogus = 1\n",
            dotenv="HASSETTE__DOTENV_TYPO=1\n",
            env={"HASSETTE__APP_DIR": "/apps", "HASSETTE__APPS__DIRECTRY": "x"},
        )

        for name in ("bogus", "HASSETTE__DOTENV_TYPO", "HASSETTE__APP_DIR", "HASSETTE__APPS__DIRECTRY"):
            assert message.count(f"{name} (from") == 1

    def test_strict_inputs_false_skips_the_check(self, cfg: Path) -> None:
        (cfg / "hassette.toml").write_text("bogus = 1\n", encoding="utf-8")

        HassetteConfig(environ={"HASSETTE__CONFIG_DIR": str(cfg), "HASSETTE__APP_DIR": "x"}, strict_inputs=False)


class TestAccepted:
    @pytest.mark.parametrize(
        "env",
        [
            pytest.param({"HASSETTE__APPS__DIRECTORY": "/apps"}, id="nested-setting"),
            pytest.param({"hassette__base_url": "http://ha:8123"}, id="lowercase"),
            pytest.param({"HASSETTE__TOKEN": "t", "HA_TOKEN": "t"}, id="token-aliases"),
            pytest.param({"HASSETTE__APPS__MY_APP__CONFIG__SENSOR": "s"}, id="app-definition-path"),
            pytest.param({"HASSETTE__APPS__MY_APP": '{"filename": "a.py"}'}, id="app-definition-json"),
            pytest.param({"HASSETTE__APPS": '{"directory": "/apps"}'}, id="json-group"),
            pytest.param({"HASSETTE_DOCKER_INSTALL_DEPS": "1", "CAR_STATUS_X": "1"}, id="other-prefixes"),
        ],
    )
    def test_process_env(self, cfg: Path, env: dict[str, str]) -> None:
        load(cfg, env=env)

    def test_unprefixed_dotenv_keys_are_ignored(self, cfg: Path) -> None:
        load(cfg, dotenv="MY_APP_SECRET=1\n")

    def test_app_definition_tables_are_opaque(self, cfg: Path) -> None:
        load(cfg, toml="[hassette.apps.my_app]\nfilename = 'a.py'\nclass_name = 'A'\nanything = 1\n")


class TestSuggestions:
    def test_typo_suggests_the_setting(self, cfg: Path) -> None:
        message = unknown_error(cfg, toml="[apps]\ndirectry = 'x'\n", env={"HASSETTE__APPS__DIRECTRY": "x"})

        assert "apps.directry (from" in message
        assert "did you mean apps.directory?" in message
        assert "did you mean HASSETTE__APPS__DIRECTORY?" in message

    def test_no_close_match_gets_no_suggestion(self, cfg: Path) -> None:
        message = unknown_error(cfg, toml="zzzqqq = 1\n")

        assert "zzzqqq (from" in message
        assert "did you mean" not in message

    def test_error_links_the_configuration_reference(self, cfg: Path) -> None:
        assert CONFIG_REFERENCE_URL in unknown_error(cfg, toml="bogus = 1\n")

    def test_reference_link_names_a_docs_page(self) -> None:
        assert CONFIG_REFERENCE_URL.startswith(DOCS_SITE_VERSION_ROOT)
        page = CONFIG_REFERENCE_URL.removeprefix(DOCS_SITE_VERSION_ROOT)

        assert (DOCS_DIR / page / "index.md").is_file()


class TestValidationError:
    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param({"env": {"HASSETTE__DATABASE__RETENTION_DAYS": "0"}}, id="invalid-nested-env-value"),
            pytest.param({"env": {"HASSETTE__WEB_API__PORT": "abc"}}, id="invalid-env-value"),
            pytest.param({"toml": "[database]\nretention_days = 0\n"}, id="invalid-toml-value"),
        ],
    )
    def test_is_a_config_error(self, cfg: Path, kwargs: dict[str, str | dict[str, str]]) -> None:
        with pytest.raises(ConfigError):
            load(cfg, **kwargs)  # pyright: ignore[reportArgumentType]

    def test_validation_message_has_no_prefix(self, cfg: Path) -> None:
        with pytest.raises(ConfigError) as exc_info:
            load(cfg, env={"HASSETTE__WEB_API__PORT": "abc"})

        assert not str(exc_info.value).startswith("Invalid configuration")


class TestExplicitLocations:
    @pytest.mark.parametrize(
        ("kwargs", "missing"),
        [
            pytest.param(
                {"environ": {"HASSETTE__CONFIG_DIR": "no-such-dir"}},
                "config directory no-such-dir",
                id="config-dir-env",
            ),
            pytest.param({"config_dir": "no-such-dir"}, "config directory no-such-dir", id="config-dir-kwarg"),
            pytest.param({"config_file": "nope.toml"}, "config file nope.toml", id="config-file"),
            pytest.param({"env_file": ["nope.env"]}, ".env file nope.env", id="env-file"),
        ],
    )
    def test_missing_explicit_location_is_a_config_error(
        self, tmp_path: Path, kwargs: dict[str, object], missing: str
    ) -> None:
        kind, name = missing.rsplit(" ", 1)

        with pytest.raises(ConfigError) as exc_info:
            HassetteConfig(cwd=tmp_path, **{"environ": {}, **kwargs})  # pyright: ignore[reportArgumentType]

        assert f"{kind} {tmp_path / name}" in str(exc_info.value)

    def test_every_missing_location_is_listed(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError) as exc_info:
            HassetteConfig(
                environ={}, cwd=tmp_path, config_dir="no-such-dir", config_file="nope.toml", env_file="nope.env"
            )

        message = str(exc_info.value)
        assert all(name in message for name in ("no-such-dir", "nope.toml", "nope.env"))

    def test_config_dir_that_is_a_file_is_an_error(self, tmp_path: Path) -> None:
        (tmp_path / "cfg").write_text("", encoding="utf-8")

        with pytest.raises(ConfigError, match="config directory"):
            HassetteConfig(environ={}, cwd=tmp_path, config_dir="cfg")

    def test_missing_searched_locations_are_skipped(self, tmp_path: Path) -> None:
        """The default search list may name directories that don't exist; only explicit ones are checked."""
        HassetteConfig(cwd=tmp_path, environ={})

    def test_client_commands_skip_the_check(self, tmp_path: Path) -> None:
        config = HassetteConfig(environ={}, cwd=tmp_path, config_dir="no-such-dir", strict_inputs=False)

        assert config.config_dir == tmp_path / "no-such-dir"


class TestUnreadableFile:
    @pytest.mark.parametrize(
        ("toml", "dotenv", "filename"),
        [
            pytest.param("[apps\n", "", "hassette.toml", id="malformed-toml"),
            pytest.param("x = '\xff'\n", "", "hassette.toml", id="toml-not-utf8"),
            pytest.param("", "HASSETTE__BASE_URL=\xff\n", ".env", id="dotenv-not-utf8"),
        ],
    )
    def test_is_a_file_config_error_naming_the_file(self, cfg: Path, toml: str, dotenv: str, filename: str) -> None:
        # latin-1 turns "\xff" into a lone 0xff byte, which is invalid UTF-8
        (cfg / "hassette.toml").write_bytes(toml.encode("latin-1"))
        (cfg / ".env").write_bytes(dotenv.encode("latin-1"))

        with pytest.raises(ConfigError) as exc_info:
            HassetteConfig(environ={"HASSETTE__CONFIG_DIR": str(cfg)})

        assert str(cfg / filename) in str(exc_info.value)


class TestConfigDirInAFile:
    @pytest.mark.parametrize(
        ("toml", "dotenv", "filename"),
        [
            pytest.param("config_dir = '/elsewhere'\n", "", "hassette.toml", id="toml"),
            pytest.param("", "HASSETTE__CONFIG_DIR=/elsewhere\n", ".env", id="dotenv"),
            pytest.param("", "HASSETTE_CONFIG_DIR=/elsewhere\n", ".env", id="dotenv-single-underscore"),
        ],
    )
    def test_is_an_error_naming_the_file_and_the_fix(self, cfg: Path, toml: str, dotenv: str, filename: str) -> None:
        with pytest.raises(ConfigError) as exc_info:
            load(cfg, toml=toml, dotenv=dotenv)

        message = str(exc_info.value)
        assert str(cfg / filename) in message
        assert "HASSETTE__CONFIG_DIR" in message
        assert "--config-dir" in message

    def test_process_env_is_the_supported_place(self, cfg: Path) -> None:
        assert load(cfg).config_dir == cfg


class TestReload:
    def test_rejected_reload_leaves_the_live_config(self, cfg: Path) -> None:
        live = load(cfg, toml="base_url = 'http://a:8123'\n")
        (cfg / "hassette.toml").write_text("base_url = 'http://b:8123'\nbogus = 1\n", encoding="utf-8")

        with pytest.raises(ConfigError):
            live.reload()

        assert live.base_url == "http://a:8123"

    def test_successful_reload_replaces_the_config(self, cfg: Path) -> None:
        live = load(cfg, toml="base_url = 'http://a:8123'\n")
        (cfg / "hassette.toml").write_text("base_url = 'http://b:8123'\n", encoding="utf-8")

        live.reload()

        assert live.base_url == "http://b:8123"

    def test_fixed_typo_clears_on_reload(self, cfg: Path) -> None:
        live = load(cfg)
        (cfg / ".env").write_text("HASSETTE__DOTENV_TYPO=1\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            live.reload()

        (cfg / ".env").write_text("", encoding="utf-8")
        live.reload()

    def test_edited_dotenv_value_beats_its_stale_copy_in_os_environ(
        self, cfg: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """startup_tasks copies .env into os.environ; a reload must read the file, not that copy."""
        live = load(cfg, dotenv="HASSETTE__VERIFY_SSL=true\n")
        monkeypatch.setenv("HASSETTE__VERIFY_SSL", "true")
        (cfg / ".env").write_text("HASSETTE__VERIFY_SSL=false\n", encoding="utf-8")

        live.reload()

        assert live.verify_ssl is False

    def test_reload_rejects_a_deleted_explicit_file_and_keeps_the_live_config(self, tmp_path: Path) -> None:
        """An editor's atomic save can briefly remove the file; the reload is rejected, not applied empty."""
        toml = tmp_path / "hassette.toml"
        toml.write_text('base_url = "http://from-file:8123"\n', encoding="utf-8")
        live = HassetteConfig(environ={}, cwd=tmp_path, config_file=toml, env_file=[])
        toml.unlink()

        with pytest.raises(ConfigError, match=str(toml)):
            live.reload()

        assert live.base_url == "http://from-file:8123"

    def test_reload_replays_init_kwargs(self, cfg: Path) -> None:
        (cfg / "hassette.toml").write_text("", encoding="utf-8")
        live = HassetteConfig(environ={"HASSETTE__CONFIG_DIR": str(cfg)}, only_apps=("kitchen",))

        live.reload()

        assert live.only_apps == ("kitchen",)

    def test_reload_resolves_relative_inputs_against_the_original_cwd(
        self, cfg: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (cfg / "hassette.toml").write_text('base_url = "http://from-cfg:8123"\n', encoding="utf-8")
        monkeypatch.chdir(cfg.parent)
        live = HassetteConfig(environ={"HASSETTE__CONFIG_DIR": cfg.name})

        monkeypatch.chdir(cfg)
        live.reload()

        assert live.config_dir == cfg
        assert live.base_url == "http://from-cfg:8123"

    def test_environment_snapshot_stays_out_of_repr(self, cfg: Path) -> None:
        (cfg / "hassette.toml").write_text("", encoding="utf-8")
        live = HassetteConfig(environ={"HASSETTE__CONFIG_DIR": str(cfg), "UNRELATED_SECRET": "hunter2"})

        assert "hunter2" not in repr(live._load_inputs)
