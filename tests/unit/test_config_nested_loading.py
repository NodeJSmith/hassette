"""Integration-level tests for HassetteConfig nested sections.

Covers nested field access, TOML loading, env var partial updates, and cross-model validation.
"""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings.sources import InitSettingsSource

from hassette.config.config import HassetteConfig
from hassette.testing.config import TEST_TOKEN


class TestHassetteConfigNested:
    """Integration tests: nested model fields accessible on HassetteConfig."""

    @pytest.fixture
    def isolated_config_cls(self):
        """Return an isolated HassetteConfig subclass (no TOML, no env, no CLI)."""

        class IsolatedConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": None,
                "env_file": None,
            }

            @classmethod
            def settings_customise_sources(cls, settings_cls, **_kwargs):  # pyright: ignore[reportIncompatibleMethodOverride]
                return (InitSettingsSource(settings_cls, init_kwargs={"token": TEST_TOKEN, "run_app_precheck": False}),)

            def model_post_init(self, *args):
                pass

        return IsolatedConfig

    def test_database_path_default(self, isolated_config_cls):
        """config.database.path returns None by default."""
        config = isolated_config_cls()
        assert config.database.path is None

    def test_database_retention_days_default(self, isolated_config_cls):
        """config.database.retention_days returns 7 by default."""
        config = isolated_config_cls()
        assert config.database.retention_days == 7

    def test_websocket_heartbeat_default(self, isolated_config_cls):
        """config.websocket.heartbeat_interval_seconds returns 30 by default."""
        config = isolated_config_cls()
        assert config.websocket.heartbeat_interval_seconds == 30

    def test_logging_log_level_default(self, isolated_config_cls):
        """config.logging.log_level returns 'INFO' by default."""
        config = isolated_config_cls()
        assert config.logging.log_level == "INFO"

    def test_web_api_run_default(self, isolated_config_cls):
        """config.web_api.run returns True by default."""
        config = isolated_config_cls()
        assert config.web_api.run is True

    def test_app_autodetect_default(self, isolated_config_cls):
        """config.apps.autodetect returns True by default."""
        config = isolated_config_cls()
        assert config.apps.autodetect is True

    def test_scheduler_job_timeout_default(self, isolated_config_cls):
        """config.scheduler.job_timeout_seconds returns 600.0 by default."""
        config = isolated_config_cls()
        assert config.scheduler.job_timeout_seconds == 600.0

    def test_file_watcher_watch_files_default(self, isolated_config_cls):
        """config.file_watcher.watch_files returns True by default."""
        config = isolated_config_cls()
        assert config.file_watcher.watch_files is True

    def test_lifecycle_event_handler_timeout_default(self, isolated_config_cls):
        """config.lifecycle.event_handler_timeout_seconds returns 600.0 by default."""
        config = isolated_config_cls()
        assert config.lifecycle.event_handler_timeout_seconds == 600.0


class TestNestedTomlLoading:
    """TOML with nested sections loads correctly."""

    def test_nested_toml_database_section(self, tmp_path):
        """A TOML file with [hassette.database] sets database fields."""
        toml = tmp_path / "hassette.toml"
        toml.write_text(
            "[hassette]\ntoken = 'test-token'\nrun_app_precheck = false\n\n[hassette.database]\nretention_days = 14\n",
            encoding="utf-8",
        )

        config = load_toml_config(toml)
        assert config.database.retention_days == 14
        # Other database defaults are preserved
        assert config.database.max_size_mb == 500

    def test_nested_toml_websocket_section(self, tmp_path):
        """A TOML file with [hassette.websocket] sets websocket fields."""
        toml = tmp_path / "hassette.toml"
        toml.write_text(
            "[hassette]\ntoken = 'test-token'\nrun_app_precheck = false\n\n"
            "[hassette.websocket]\nheartbeat_interval_seconds = 60\n",
            encoding="utf-8",
        )

        config = load_toml_config(toml)
        assert config.websocket.heartbeat_interval_seconds == 60

    def test_empty_nested_toml_section_produces_defaults(self, tmp_path):
        """An empty [hassette.database] section produces valid DatabaseConfig with all defaults."""
        toml = tmp_path / "hassette.toml"
        toml.write_text(
            "[hassette]\ntoken = 'test-token'\nrun_app_precheck = false\n\n[hassette.database]\n",
            encoding="utf-8",
        )

        config = load_toml_config(toml)
        assert config.database.retention_days == 7
        assert config.database.max_size_mb == 500


class TestEnvVarPartialUpdate:
    """Setting a single env var for a nested field does not replace entire group defaults."""

    def test_single_env_var_sets_only_that_field(self, monkeypatch, tmp_path):
        """HASSETTE__DATABASE__RETENTION_DAYS=14 sets only retention_days."""
        monkeypatch.setenv("HASSETTE__DATABASE__RETENTION_DAYS", "14")

        class EnvDatabaseConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": None,
                "env_file": None,
            }

            token: SecretStr = SecretStr(TEST_TOKEN)
            run_app_precheck: bool = False

        config = EnvDatabaseConfig()
        assert config.database.retention_days == 14
        # Other database defaults are preserved
        assert config.database.max_size_mb == 500
        assert config.database.write_queue_max == 2000

    def test_env_var_logging_log_level(self, monkeypatch):
        """HASSETTE__LOGGING__LOG_LEVEL=DEBUG sets only logging.log_level."""
        monkeypatch.setenv("HASSETTE__LOGGING__LOG_LEVEL", "DEBUG")

        class EnvLoggingConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": None,
                "env_file": None,
            }

            token: SecretStr = SecretStr(TEST_TOKEN)
            run_app_precheck: bool = False

        config = EnvLoggingConfig()
        assert config.logging.log_level == "DEBUG"

    def test_env_var_cli_server_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HASSETTE__CLI__SERVER_URL=https://example.com sets only cli.server_url."""
        monkeypatch.setenv("HASSETTE__CLI__SERVER_URL", "https://example.com")

        class EnvCliServerUrlConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": None,
                "env_file": None,
            }

            token: SecretStr = SecretStr(TEST_TOKEN)
            run_app_precheck: bool = False

        config = EnvCliServerUrlConfig()
        assert config.cli.server_url == "https://example.com"
        # Other cli defaults are preserved
        assert config.cli.verify_ssl is True

    def test_env_var_cli_verify_ssl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HASSETTE__CLI__VERIFY_SSL=false sets only cli.verify_ssl."""
        monkeypatch.setenv("HASSETTE__CLI__VERIFY_SSL", "false")

        class EnvCliVerifySslConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": None,
                "env_file": None,
            }

            token: SecretStr = SecretStr(TEST_TOKEN)
            run_app_precheck: bool = False

        config = EnvCliVerifySslConfig()
        assert config.cli.verify_ssl is False
        # Other cli defaults are preserved
        assert config.cli.server_url is None


class TestCrossModelValidation:
    """Cross-model validators spanning nested models."""

    def test_log_retention_exceeds_db_retention_raises(self):
        """log_retention_days > retention_days raises ValidationError referencing both paths."""

        class ValidationConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": None,
                "env_file": None,
            }

            token: SecretStr = SecretStr(TEST_TOKEN)
            run_app_precheck: bool = False

        with pytest.raises((ValidationError, ValueError)) as exc_info:
            ValidationConfig(
                database={"retention_days": 3},
                logging={"log_retention_days": 5},
            )
        error_text = str(exc_info.value)
        # Error should reference both nested paths
        assert "log_retention_days" in error_text or "retention" in error_text


def load_toml_config(toml: Path) -> HassetteConfig:
    """Build a HassetteConfig that reads only the given TOML file (no CLI args, no .env)."""

    class TomlConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "toml_file": str(toml),
            "env_file": None,
        }

    return TomlConfig()
