import os
import sys
import textwrap
from pathlib import Path

import pytest

from hassette import HassetteConfig, context
from hassette.test_utils.fixtures import build_harness, run_hassette_startup_tasks

APP_KEY = "env_reader"
TOKEN = "test-token"

ENV_IMPORT_KEY = "HASSETTE_TEST_APP_IMPORT"
ENV_SETTINGS_KEY = "MY_SECRET"

ENV_READER_FILENAME = "env_reader_app.py"
ENV_SETTINGS_FILENAME = "env_settings_app.py"

ENV_READER_CLASS = "EnvReaderApp"
ENV_SETTINGS_CLASS = "SettingsApp"

TOML_FILENAME = "hassette.toml"
ENV_IMPORT_FILENAME = "app_import.env"
ENV_CUSTOM_FILENAME = "custom.env"


def _cleanup_env(*keys: str) -> None:
    for key in keys:
        os.environ.pop(key, None)


def _new_unique_app_dir(tmp_path: Path) -> tuple[str, Path]:
    """Create a unique apps dir for test-created app modules."""

    pkg_name = "testapps_" + os.urandom(6).hex()
    app_dir = tmp_path / pkg_name
    app_dir.mkdir(parents=True, exist_ok=True)
    return pkg_name, app_dir


def _clear_app_import_caches(pkg_name: str, module_name: str) -> None:
    """Avoid cross-test module collisions and cached failures/successes."""

    sys.modules.pop(f"{pkg_name}.{module_name}", None)
    sys.modules.pop(pkg_name, None)

    from hassette.utils import app_utils

    app_utils.LOADED_CLASSES.clear()
    app_utils.FAILED_TO_LOAD_CLASSES.clear()


def _write_env_reader_app(app_dir: Path) -> None:
    path = app_dir / ENV_READER_FILENAME

    path.write_text(
        textwrap.dedent(
            f"""
            import os
            from hassette import App

            READ_AT_IMPORT = os.getenv({ENV_IMPORT_KEY!r}, 'NOT_FOUND')

            class {ENV_READER_CLASS}(App):
                async def on_initialize(self) -> None:
                    return
            """
        ).lstrip(),
        encoding="utf-8",
    )


def _write_env_settings_app(app_dir: Path) -> None:
    path = app_dir / ENV_SETTINGS_FILENAME
    path.write_text(
        textwrap.dedent(
            f"""
            from hassette import App, AppConfig

            class SettingsConfig(AppConfig):
                {ENV_SETTINGS_KEY.lower()}: str

            class {ENV_SETTINGS_CLASS}(App[SettingsConfig]):
                async def on_initialize(self) -> None:
                    self.seen = getattr(self.app_config, {ENV_SETTINGS_KEY.lower()!r})
            """
        ).lstrip(),
        encoding="utf-8",
    )


def _write_env_file(path: Path, key: str, value: str) -> None:
    path.write_text(f"{key}={value}\n", encoding="utf-8")


def _write_toml(
    toml_file: Path,
    *,
    app_dir: Path,
    run_app_precheck: bool,
    filename: str,
    class_name: str,
) -> None:
    toml_file.write_text(
        textwrap.dedent(
            f"""
            [hassette]
            app_dir = {app_dir.as_posix()!r}
            autodetect_apps = false
            run_app_precheck = {str(run_app_precheck).lower()}

            [apps.{APP_KEY}]
            enabled = true
            filename = {filename!r}
            class_name = {class_name!r}
            app_dir = {app_dir.as_posix()!r}
            """
        ).lstrip(),
        encoding="utf-8",
    )


def _build_config_class(*, toml_file: Path, env_files: list[Path]):
    class _TestConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "toml_file": [toml_file],
            "env_file": env_files,
        }

        token: str = TOKEN

    return _TestConfig


async def test_import_dot_env_files_makes_values_visible_during_app_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """With import_dot_env_files=True, Hassette loads env_files before app precheck imports."""

    pkg_name, app_dir = _new_unique_app_dir(tmp_path)
    _write_env_reader_app(app_dir)

    env_file = tmp_path / ENV_IMPORT_FILENAME
    _write_env_file(env_file, ENV_IMPORT_KEY, "from_dotenv")

    toml_file = tmp_path / TOML_FILENAME
    _write_toml(
        toml_file,
        app_dir=app_dir,
        run_app_precheck=True,
        filename=ENV_READER_FILENAME,
        class_name=ENV_READER_CLASS,
    )

    monkeypatch.delenv(ENV_IMPORT_KEY, raising=False)
    _clear_app_import_caches(pkg_name, "env_reader_app")

    app_import_config = _build_config_class(toml_file=toml_file, env_files=[env_file])
    config = app_import_config(import_dot_env_files=True)
    with context.use_hassette_config(config):
        run_hassette_startup_tasks(config)

    mod = sys.modules.get(f"{pkg_name}.env_reader_app")
    assert mod is not None, "Expected app module to be imported during precheck"
    assert mod.READ_AT_IMPORT == "from_dotenv"  # type: ignore[attr-defined]
    _cleanup_env(ENV_IMPORT_KEY)


async def test_import_dot_env_files_disabled_not_visible_during_app_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Without import_dot_env_files, app import-time env reads should not see custom env_files values."""

    pkg_name, app_dir = _new_unique_app_dir(tmp_path)
    _write_env_reader_app(app_dir)

    env_file = tmp_path / ENV_IMPORT_FILENAME
    _write_env_file(env_file, ENV_IMPORT_KEY, "from_dotenv")

    toml_file = tmp_path / TOML_FILENAME
    _write_toml(
        toml_file,
        app_dir=app_dir,
        run_app_precheck=True,
        filename=ENV_READER_FILENAME,
        class_name=ENV_READER_CLASS,
    )

    monkeypatch.delenv(ENV_IMPORT_KEY, raising=False)
    _clear_app_import_caches(pkg_name, "env_reader_app")

    app_import_config = _build_config_class(toml_file=toml_file, env_files=[env_file])
    config = app_import_config(import_dot_env_files=False)
    with context.use_hassette_config(config):
        run_hassette_startup_tasks(config)

    mod = sys.modules.get(f"{pkg_name}.env_reader_app")
    assert mod is not None, "Expected app module to be imported during precheck"
    assert mod.READ_AT_IMPORT == "NOT_FOUND"
    _cleanup_env(ENV_IMPORT_KEY)


async def test_app_config_can_read_from_os_environ(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """AppConfig subclasses (BaseSettings) can read required fields from os.environ."""

    from hassette.test_utils.harness import wait_for

    monkeypatch.chdir(tmp_path)

    _cleanup_env(ENV_SETTINGS_KEY)
    monkeypatch.setenv(ENV_SETTINGS_KEY, "from_os_environ")

    pkg_name, app_dir = _new_unique_app_dir(tmp_path)
    _write_env_settings_app(app_dir)

    toml_file = tmp_path / TOML_FILENAME
    _write_toml(
        toml_file,
        app_dir=app_dir,
        run_app_precheck=False,
        filename=ENV_SETTINGS_FILENAME,
        class_name=ENV_SETTINGS_CLASS,
    )

    _clear_app_import_caches(pkg_name, "env_settings_app")

    app_settings_config = _build_config_class(toml_file=toml_file, env_files=[])
    config = app_settings_config(import_dot_env_files=False)

    async with build_harness(config=config, use_bus=True, use_app_handler=True, use_scheduler=True) as harness:
        await wait_for(
            lambda: (
                harness.hassette.get_app("env_reader") is not None
                and getattr(harness.hassette.get_app("env_reader"), "seen", None) == "from_os_environ"
            ),
            timeout=2,
            desc="SettingsApp initialized with env value",
        )
        app = harness.hassette.get_app("env_reader")
        assert app is not None
        assert getattr(app, "seen", None) == "from_os_environ"

    _cleanup_env(ENV_SETTINGS_KEY)


async def test_app_config_does_not_see_custom_env_file_without_import_dot_env_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """If an env var exists only in HassetteConfig.env_files, AppConfig won't see it unless imported to os.environ."""

    from hassette.test_utils.harness import wait_for

    monkeypatch.chdir(tmp_path)

    _cleanup_env(ENV_SETTINGS_KEY)

    pkg_name, app_dir = _new_unique_app_dir(tmp_path)
    _write_env_settings_app(app_dir)

    custom_env = tmp_path / ENV_CUSTOM_FILENAME
    _write_env_file(custom_env, ENV_SETTINGS_KEY, "from_custom_env")

    toml_file = tmp_path / TOML_FILENAME
    _write_toml(
        toml_file,
        app_dir=app_dir,
        run_app_precheck=False,
        filename=ENV_SETTINGS_FILENAME,
        class_name=ENV_SETTINGS_CLASS,
    )

    _clear_app_import_caches(pkg_name, "env_settings_app")

    custom_env_config = _build_config_class(toml_file=toml_file, env_files=[custom_env])
    config = custom_env_config(import_dot_env_files=False)
    run_hassette_startup_tasks(config)

    async with build_harness(config=config, use_bus=True, use_app_handler=True, use_scheduler=True) as harness:
        await wait_for(
            lambda: (harness.hassette.get_app("env_reader") is not None)
            or ("env_reader" in (harness.hassette._app_handler.failed_apps if harness.hassette._app_handler else {})),
            timeout=2,
            desc="SettingsApp started or failed",
        )
        assert harness.hassette.get_app("env_reader") is None
        assert harness.hassette._app_handler is not None
        assert "env_reader" in harness.hassette._app_handler.failed_apps

    _cleanup_env(ENV_SETTINGS_KEY)


async def test_app_config_sees_custom_env_file_when_import_dot_env_files_true(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """With import_dot_env_files=True, custom env files become visible to AppConfig via os.environ."""

    from hassette.test_utils.harness import wait_for

    monkeypatch.chdir(tmp_path)

    _cleanup_env(ENV_SETTINGS_KEY)

    pkg_name, app_dir = _new_unique_app_dir(tmp_path)
    _write_env_settings_app(app_dir)

    custom_env = tmp_path / ENV_CUSTOM_FILENAME
    _write_env_file(custom_env, ENV_SETTINGS_KEY, "from_custom_env")

    toml_file = tmp_path / TOML_FILENAME
    _write_toml(
        toml_file,
        app_dir=app_dir,
        run_app_precheck=False,
        filename=ENV_SETTINGS_FILENAME,
        class_name=ENV_SETTINGS_CLASS,
    )

    _clear_app_import_caches(pkg_name, "env_settings_app")

    custom_env_config = _build_config_class(toml_file=toml_file, env_files=[custom_env])
    config = custom_env_config(import_dot_env_files=True)
    with context.use_hassette_config(config):
        run_hassette_startup_tasks(config)

    async with build_harness(config=config, use_bus=True, use_app_handler=True, use_scheduler=True) as harness:
        await wait_for(
            lambda: (
                harness.hassette.get_app("env_reader") is not None
                and getattr(harness.hassette.get_app("env_reader"), "seen", None) == "from_custom_env"
            ),
            timeout=2,
            desc="SettingsApp initialized with env value",
        )
        app = harness.hassette.get_app("env_reader")
        assert app is not None
        assert getattr(app, "seen", None) == "from_custom_env"

    _cleanup_env(ENV_SETTINGS_KEY)
