import os
import sys
from pathlib import Path

import pytest

from hassette import context
from hassette.testing import HassetteHarness, build_harness, wait_for
from tests.support.app_staging_helpers import (
    ENV_CUSTOM_FILENAME,
    ENV_IMPORT_FILENAME,
    ENV_IMPORT_KEY,
    ENV_READER_CLASS,
    ENV_READER_FILENAME,
    ENV_SETTINGS_CLASS,
    ENV_SETTINGS_FILENAME,
    ENV_SETTINGS_KEY,
    build_config_class,
    cleanup_env,
    stage_app,
    write_env_reader_app,
    write_env_settings_app,
)
from tests.support.fixtures import run_hassette_startup_tasks


async def test_import_dot_env_files_makes_values_visible_during_app_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """With import_dot_env_files=True, Hassette loads env_files before app precheck imports."""
    staged = stage_app(
        tmp_path,
        writer=write_env_reader_app,
        filename=ENV_READER_FILENAME,
        class_name=ENV_READER_CLASS,
        module_name="env_reader_app",
        env_file_name=ENV_IMPORT_FILENAME,
        env_key=ENV_IMPORT_KEY,
        env_value="from_dotenv",
    )
    assert staged.env_file is not None

    monkeypatch.delenv(ENV_IMPORT_KEY, raising=False)

    app_import_config = build_config_class(
        toml_file=staged.toml_file, env_files=[staged.env_file], scratch_dir=tmp_path / "data"
    )
    config = app_import_config(import_dot_env_files=True)
    with context.use_hassette_config(config):
        run_hassette_startup_tasks(config)

    mod = sys.modules.get(f"{staged.pkg_name}.env_reader_app")
    assert mod is not None, "Expected app module to be imported during precheck"
    assert mod.READ_AT_IMPORT == "from_dotenv"  # pyright: ignore[reportAttributeAccessIssue]
    cleanup_env(ENV_IMPORT_KEY)


async def test_import_dot_env_files_disabled_not_visible_during_app_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Without import_dot_env_files, app import-time env reads should not see custom env_files values."""
    staged = stage_app(
        tmp_path,
        writer=write_env_reader_app,
        filename=ENV_READER_FILENAME,
        class_name=ENV_READER_CLASS,
        module_name="env_reader_app",
        env_file_name=ENV_IMPORT_FILENAME,
        env_key=ENV_IMPORT_KEY,
        env_value="from_dotenv",
    )
    assert staged.env_file is not None

    monkeypatch.delenv(ENV_IMPORT_KEY, raising=False)

    app_import_config = build_config_class(
        toml_file=staged.toml_file, env_files=[staged.env_file], scratch_dir=tmp_path / "data"
    )
    config = app_import_config(import_dot_env_files=False)
    with context.use_hassette_config(config):
        run_hassette_startup_tasks(config)

    mod = sys.modules.get(f"{staged.pkg_name}.env_reader_app")
    assert mod is not None, "Expected app module to be imported during precheck"
    assert mod.READ_AT_IMPORT == "NOT_FOUND"
    cleanup_env(ENV_IMPORT_KEY)


async def test_app_config_can_read_from_os_environ(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """AppConfig subclasses (BaseSettings) can read required fields from os.environ."""
    monkeypatch.chdir(tmp_path)

    cleanup_env(ENV_SETTINGS_KEY)
    monkeypatch.setenv(ENV_SETTINGS_KEY, "from_os_environ")

    staged = stage_app(
        tmp_path,
        writer=write_env_settings_app,
        filename=ENV_SETTINGS_FILENAME,
        class_name=ENV_SETTINGS_CLASS,
        module_name="env_settings_app",
    )

    app_settings_config = build_config_class(toml_file=staged.toml_file, env_files=[], scratch_dir=tmp_path / "data")
    config = app_settings_config(import_dot_env_files=False)

    async with build_harness(HassetteHarness(config).with_app_handler().with_scheduler()) as harness:
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

    cleanup_env(ENV_SETTINGS_KEY)


async def test_app_config_reads_hassette_env_files_without_import_dot_env_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """AppConfig reads the same .env files as HassetteConfig, so it sees their values without an os.environ import."""
    monkeypatch.chdir(tmp_path)

    cleanup_env(ENV_SETTINGS_KEY)

    staged = stage_app(
        tmp_path,
        writer=write_env_settings_app,
        filename=ENV_SETTINGS_FILENAME,
        class_name=ENV_SETTINGS_CLASS,
        module_name="env_settings_app",
        env_file_name=ENV_CUSTOM_FILENAME,
        env_key=ENV_SETTINGS_KEY,
        env_value="from_custom_env",
    )
    assert staged.env_file is not None

    custom_env_config = build_config_class(
        toml_file=staged.toml_file, env_files=[staged.env_file], scratch_dir=tmp_path / "data"
    )
    config = custom_env_config(import_dot_env_files=False)
    run_hassette_startup_tasks(config)

    async with build_harness(HassetteHarness(config).with_app_handler().with_scheduler()) as harness:
        await wait_for(
            lambda: getattr(harness.hassette.get_app("env_reader"), "seen", None) == "from_custom_env",
            timeout=2,
            desc="SettingsApp initialized with the value from Hassette's .env file",
        )
        assert ENV_SETTINGS_KEY not in os.environ

    cleanup_env(ENV_SETTINGS_KEY)


async def test_app_config_sees_custom_env_file_when_import_dot_env_files_true(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """With import_dot_env_files=True, custom env files become visible to AppConfig via os.environ."""
    monkeypatch.chdir(tmp_path)

    cleanup_env(ENV_SETTINGS_KEY)

    staged = stage_app(
        tmp_path,
        writer=write_env_settings_app,
        filename=ENV_SETTINGS_FILENAME,
        class_name=ENV_SETTINGS_CLASS,
        module_name="env_settings_app",
        env_file_name=ENV_CUSTOM_FILENAME,
        env_key=ENV_SETTINGS_KEY,
        env_value="from_custom_env",
    )
    assert staged.env_file is not None

    custom_env_config = build_config_class(
        toml_file=staged.toml_file, env_files=[staged.env_file], scratch_dir=tmp_path / "data"
    )
    config = custom_env_config(import_dot_env_files=True)
    with context.use_hassette_config(config):
        run_hassette_startup_tasks(config)

    async with build_harness(HassetteHarness(config).with_app_handler().with_scheduler()) as harness:
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

    cleanup_env(ENV_SETTINGS_KEY)
