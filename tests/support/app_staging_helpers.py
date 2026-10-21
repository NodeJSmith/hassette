"""Helpers that stage a throwaway app package on disk for app-precheck tests.

``stage_app()`` is the entry point: it writes an app module, an optional ``.env`` file,
and a ``hassette.toml`` pointing at the app, then clears the app-import caches so the
next precheck imports the freshly written module.
"""

import os
import sys
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import SecretStr

from hassette import HassetteConfig
from hassette.testing.config import TEST_TOKEN
from hassette.utils import app_utils

APP_KEY = "env_reader"
ENV_IMPORT_KEY = "HASSETTE_TEST_APP_IMPORT"
ENV_SETTINGS_KEY = "MY_SECRET"

ENV_READER_FILENAME = "env_reader_app.py"
ENV_SETTINGS_FILENAME = "env_settings_app.py"

ENV_READER_CLASS = "EnvReaderApp"
ENV_SETTINGS_CLASS = "SettingsApp"

TOML_FILENAME = "hassette.toml"
ENV_IMPORT_FILENAME = "app_import.env"
ENV_CUSTOM_FILENAME = "custom.env"


def cleanup_env(*keys: str) -> None:
    for key in keys:
        os.environ.pop(key, None)


def new_unique_app_dir(tmp_path: Path) -> tuple[str, Path]:
    """Create a unique apps dir for test-created app modules."""
    pkg_name = "testapps_" + os.urandom(6).hex()
    app_dir = tmp_path / pkg_name
    app_dir.mkdir(parents=True, exist_ok=True)
    return pkg_name, app_dir


def clear_app_import_caches(pkg_name: str, module_name: str) -> None:
    """Avoid cross-test module collisions and cached failures/successes."""
    sys.modules.pop(f"{pkg_name}.{module_name}", None)
    sys.modules.pop(pkg_name, None)
    clear_loaded_class_caches()


def clear_loaded_class_caches() -> None:
    """Drop app_utils' cached class load successes and failures."""
    app_utils.LOADED_CLASSES.clear()
    app_utils.FAILED_TO_LOAD_CLASSES.clear()


def write_env_reader_app(app_dir: Path) -> None:
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


def write_env_settings_app(app_dir: Path) -> None:
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


def write_env_file(path: Path, key: str, value: str) -> None:
    path.write_text(f"{key}={value}\n", encoding="utf-8")


def write_toml(
    toml_file: Path,
    *,
    app_dir: Path,
    filename: str,
    class_name: str,
) -> None:
    toml_file.write_text(
        textwrap.dedent(
            f"""
            [hassette.apps]
            directory = {app_dir.as_posix()!r}

            [hassette.apps.{APP_KEY}]
            enabled = true
            filename = {filename!r}
            class_name = {class_name!r}
            app_dir = {app_dir.as_posix()!r}
            """
        ).lstrip(),
        encoding="utf-8",
    )


def build_config_class(*, toml_file: Path, env_files: list[Path], scratch_dir: Path):
    class _TestConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "toml_file": [toml_file],
            "env_file": env_files,
        }

        token: SecretStr = SecretStr(TEST_TOKEN)
        data_dir: Path = scratch_dir

    return _TestConfig


@dataclass(frozen=True)
class StagedApp:
    pkg_name: str
    app_dir: Path
    toml_file: Path
    env_file: Path | None


def stage_app(
    tmp_path: Path,
    *,
    writer: Callable[[Path], None],
    filename: str,
    class_name: str,
    module_name: str,
    env_file_name: str | None = None,
    env_key: str | None = None,
    env_value: str | None = None,
) -> StagedApp:
    """Write an app package, optional env file, and hassette.toml under ``tmp_path``, then clear import caches."""
    pkg_name, app_dir = new_unique_app_dir(tmp_path)
    writer(app_dir)

    env_file: Path | None = None
    if env_file_name is not None:
        if env_key is None or env_value is None:
            raise ValueError("env_key and env_value are required when env_file_name is given")
        env_file = tmp_path / env_file_name
        write_env_file(env_file, env_key, env_value)

    toml_file = tmp_path / TOML_FILENAME
    write_toml(toml_file, app_dir=app_dir, filename=filename, class_name=class_name)

    clear_app_import_caches(pkg_name, module_name)
    return StagedApp(pkg_name=pkg_name, app_dir=app_dir, toml_file=toml_file, env_file=env_file)
