import os
import sys
import textwrap
from pathlib import Path

import dotenv
import pytest

from hassette import HassetteConfig, context
from hassette.config.defaults import AUTODETECT_EXCLUDE_DIRS_DEFAULT
from hassette.test_utils import run_hassette_startup_tasks


def _cleanup_env(*keys: str) -> None:
    for key in keys:
        os.environ.pop(key, None)


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


def test_env_files_can_be_configured_as_multiple_files(monkeypatch, tmp_path):
    """env_file accepts multiple paths; env_files returns existing resolved paths.

    Current behavior (documented by this test):
    - `HassetteConfig.model_config['env_file']` may be a list/tuple of paths.
    - `HassetteConfig.env_files` is a `set[Path]` (order is not preserved).
    - Missing files are silently filtered out.
    """

    env1 = tmp_path / "one.env"
    env2 = tmp_path / "two.env"
    missing = tmp_path / "missing.env"
    env1.write_text("HASSETTE_TEST_ENV_ONE=1\n", encoding="utf-8")
    env2.write_text("HASSETTE_TEST_ENV_TWO=2\n", encoding="utf-8")

    monkeypatch.delenv("HASSETTE_TEST_ENV_ONE", raising=False)
    monkeypatch.delenv("HASSETTE_TEST_ENV_TWO", raising=False)

    class MultiEnvConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "env_file": [env1, env2, missing],
            "toml_file": [],
        }

        token: str = "test-token"
        run_app_precheck: bool = False

    config = MultiEnvConfig()
    assert config.env_files == {env1.resolve(), env2.resolve()}


def test_env_file_contributes_to_settings_without_mutating_os_environ(monkeypatch, tmp_path):
    """The pydantic-settings dotenv source affects config values, but does not write into os.environ."""

    env_file = tmp_path / ".env"
    env_file.write_text("HASSETTE__LOG_LEVEL=DEBUG\n", encoding="utf-8")

    monkeypatch.delenv("HASSETTE__LOG_LEVEL", raising=False)

    class DotenvOnlyConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "env_file": [env_file],
            "toml_file": [],
        }

        token: str = "test-token"
        run_app_precheck: bool = False
        import_dot_env_files: bool = False

    config = DotenvOnlyConfig()

    assert config.log_level == "DEBUG"
    assert os.getenv("HASSETTE__LOG_LEVEL") is None


async def test_import_dot_env_files_true_loads_vars_into_os_environ(monkeypatch, tmp_path):
    """When import_dot_env_files=True, Hassette loads env_files into os.environ at startup."""

    env_file = tmp_path / "hassette.env"
    env_file.write_text("HASSETTE_TEST_IMPORTED=from_dotenv\n", encoding="utf-8")
    monkeypatch.delenv("HASSETTE_TEST_IMPORTED", raising=False)

    class ImportingConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "env_file": [env_file],
            "toml_file": [],
        }

        token: str = "test-token"
        run_app_precheck: bool = False

    config = ImportingConfig(import_dot_env_files=True)
    run_hassette_startup_tasks(config)
    assert os.getenv("HASSETTE_TEST_IMPORTED") == "from_dotenv"
    _cleanup_env("HASSETTE_TEST_IMPORTED")


async def test_import_dot_env_files_false_does_not_touch_os_environ(monkeypatch, tmp_path):
    """When import_dot_env_files=False, Hassette does not inject dotenv keys into os.environ."""

    env_file = tmp_path / "hassette.env"
    env_file.write_text("HASSETTE_TEST_IMPORTED=from_dotenv\n", encoding="utf-8")
    monkeypatch.delenv("HASSETTE_TEST_IMPORTED", raising=False)

    class NonImportingConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "env_file": [env_file],
            "toml_file": [],
        }

        token: str = "test-token"
        run_app_precheck: bool = False

    config = NonImportingConfig(import_dot_env_files=False)
    run_hassette_startup_tasks(config)
    assert os.getenv("HASSETTE_TEST_IMPORTED") is None
    _cleanup_env("HASSETTE_TEST_IMPORTED")


async def test_import_dot_env_files_does_not_override_existing_environ(monkeypatch, tmp_path):
    """Current behavior: dotenv import does not override existing os.environ values."""

    env_file = tmp_path / "hassette.env"
    env_file.write_text("HASSETTE_TEST_EXISTING=from_dotenv\n", encoding="utf-8")

    monkeypatch.setenv("HASSETTE_TEST_EXISTING", "preexisting")

    class NonOverridingConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "env_file": [env_file],
            "toml_file": [],
        }

        token: str = "test-token"
        run_app_precheck: bool = False

    config = NonOverridingConfig(import_dot_env_files=True)
    run_hassette_startup_tasks(config)
    assert os.getenv("HASSETTE_TEST_EXISTING") == "preexisting"
    _cleanup_env("HASSETTE_TEST_EXISTING")


async def test_multiple_env_files_import_non_conflicting_keys(monkeypatch, tmp_path):
    """Multiple env files can be imported; non-conflicting keys should all show up in os.environ."""

    env1 = tmp_path / "one.env"
    env2 = tmp_path / "two.env"
    env1.write_text("HASSETTE_TEST_MULTI_ONE=1\n", encoding="utf-8")
    env2.write_text("HASSETTE_TEST_MULTI_TWO=2\n", encoding="utf-8")

    monkeypatch.delenv("HASSETTE_TEST_MULTI_ONE", raising=False)
    monkeypatch.delenv("HASSETTE_TEST_MULTI_TWO", raising=False)

    class MultiImportConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "env_file": [env1, env2],
            "toml_file": [],
        }

        token: str = "test-token"
        run_app_precheck: bool = False

    config = MultiImportConfig(import_dot_env_files=True)
    run_hassette_startup_tasks(config)
    assert os.getenv("HASSETTE_TEST_MULTI_ONE") == "1"
    assert os.getenv("HASSETTE_TEST_MULTI_TWO") == "2"
    _cleanup_env("HASSETTE_TEST_MULTI_ONE", "HASSETTE_TEST_MULTI_TWO")


async def test_multiple_env_files_conflicting_key_is_effectively_order_dependent(monkeypatch, tmp_path):
    """Current behavior: with conflicting keys across multiple env files, the winner is order-dependent.

    Why this exists:
    - `HassetteConfig.env_files` is a `set`, so load order is not specified.
    - python-dotenv's `load_dotenv()` defaults to `override=False`, so the first file loaded wins.

    This test documents the current outcome without assuming a deterministic order.
    """

    env1 = tmp_path / "one.env"
    env2 = tmp_path / "two.env"
    env1.write_text("HASSETTE_TEST_CONFLICT=one\n", encoding="utf-8")
    env2.write_text("HASSETTE_TEST_CONFLICT=two\n", encoding="utf-8")

    monkeypatch.delenv("HASSETTE_TEST_CONFLICT", raising=False)

    class MultiConflictConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "env_file": [env1, env2],
            "toml_file": [],
        }

        token: str = "test-token"
        run_app_precheck: bool = False

    config = MultiConflictConfig(import_dot_env_files=True)
    run_hassette_startup_tasks(config)

    assert os.getenv("HASSETTE_TEST_CONFLICT") in {"one", "two"}
    _cleanup_env("HASSETTE_TEST_CONFLICT")


@pytest.mark.xfail(reason="Spec: env_files should preserve declared ordering (currently it returns a set).")
def test_spec_env_files_preserves_declared_order(tmp_path):
    """Spec: env_files should preserve declared ordering.

    This is intentionally written to fail deterministically until `env_files` becomes an ordered
    sequence (e.g. list/tuple) rather than a set.
    """

    env1 = tmp_path / "one.env"
    env2 = tmp_path / "two.env"
    env1.write_text("A=1\n", encoding="utf-8")
    env2.write_text("B=2\n", encoding="utf-8")

    class OrderedEnvConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "env_file": [env1, env2],
            "toml_file": [],
        }

        token: str = "test-token"
        run_app_precheck: bool = False

    config = OrderedEnvConfig()
    assert isinstance(config.env_files, (list, tuple))


@pytest.mark.xfail(
    reason=(
        "Spec: dotenv import should apply env_files in declared order and later files should override earlier ones. "
        "Current behavior uses a set (unordered) and load_dotenv(override=False)."
    )
)
async def test_spec_last_env_file_wins_on_conflicts(monkeypatch, tmp_path):
    """Spec: later env files override earlier ones for conflicting keys.

    This is intentionally written to fail deterministically until env_files ordering and override semantics
    are made explicit.
    """

    env1 = tmp_path / "one.env"
    env2 = tmp_path / "two.env"
    env1.write_text("HASSETTE_TEST_CONFLICT_SPEC=one\n", encoding="utf-8")
    env2.write_text("HASSETTE_TEST_CONFLICT_SPEC=two\n", encoding="utf-8")

    monkeypatch.delenv("HASSETTE_TEST_CONFLICT_SPEC", raising=False)

    class MultiConflictSpecConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "env_file": [env1, env2],
            "toml_file": [],
        }

        token: str = "test-token"
        run_app_precheck: bool = False

    config = MultiConflictSpecConfig(import_dot_env_files=True)

    # Spec requires ordered env_files.
    assert isinstance(config.env_files, (list, tuple))

    run_hassette_startup_tasks(config)

    # Spec requires later files override earlier files.
    assert os.getenv("HASSETTE_TEST_CONFLICT_SPEC") == "two"
    _cleanup_env("HASSETTE_TEST_CONFLICT_SPEC")


async def test_import_dot_env_files_makes_values_visible_during_app_import(monkeypatch, tmp_path):
    """Document whether apps can read injected dotenv values at import time.

    Expectation captured by this test:
    - With `import_dot_env_files=True`, Hassette loads env files before app precheck imports.
    - Therefore an app module that reads os.environ at import time should see those values.
    """

    # Create a unique apps package name to avoid cross-test module collisions.
    pkg_name = "testapps_" + os.urandom(6).hex()
    app_dir = tmp_path / pkg_name
    app_dir.mkdir(parents=True, exist_ok=True)

    app_py = app_dir / "env_reader_app.py"
    app_py.write_text(
        textwrap.dedent(
            """
            import os

            from hassette import App, AppConfig

            READ_AT_IMPORT = os.getenv("HASSETTE_TEST_APP_IMPORT")


            class EnvReaderConfig(AppConfig):
                pass


            class EnvReaderApp(App[EnvReaderConfig]):
                async def on_initialize(self) -> None:
                    return
            """
        ).lstrip(),
        encoding="utf-8",
    )

    env_file = tmp_path / "app_import.env"
    env_file.write_text("HASSETTE_TEST_APP_IMPORT=from_dotenv\n", encoding="utf-8")

    toml_file = tmp_path / "hassette.toml"
    toml_file.write_text(
        textwrap.dedent(
            f"""
            [hassette]
            app_dir = {app_dir.as_posix()!r}
            autodetect_apps = false
            run_app_precheck = true

            [apps.env_reader]
            enabled = true
            filename = "env_reader_app.py"
            class_name = "EnvReaderApp"
            app_dir = {app_dir.as_posix()!r}
            config = {{}}
            """
        ).lstrip(),
        encoding="utf-8",
    )

    monkeypatch.delenv("HASSETTE_TEST_APP_IMPORT", raising=False)

    # Ensure a clean import, both for our module and our namespace package.
    sys.modules.pop(f"{pkg_name}.env_reader_app", None)
    sys.modules.pop(pkg_name, None)
    from hassette.utils import app_utils

    app_utils.LOADED_CLASSES.clear()
    app_utils.FAILED_TO_LOAD_CLASSES.clear()

    class AppImportConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "toml_file": [toml_file],
            "env_file": [env_file],
        }

        token: str = "test-token"

    config = AppImportConfig(import_dot_env_files=True)
    with context.use_hassette_config(config):
        run_hassette_startup_tasks(config)

    mod = sys.modules.get(f"{pkg_name}.env_reader_app")
    assert mod is not None, "Expected app module to be imported during precheck"
    assert mod.READ_AT_IMPORT == "from_dotenv"  # type: ignore[attr-defined]
    _cleanup_env("HASSETTE_TEST_APP_IMPORT")
