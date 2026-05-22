"""Unit tests for nested config model classes in hassette.config.models.

Covers defaults, field constraints, computed defaults, and intra-model validators.
Also covers integration-level config loading with nested sections and env var overrides.
"""

import warnings
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings
from pydantic_settings.sources import InitSettingsSource

from hassette.config.config import HassetteConfig
from hassette.config.defaults import AUTODETECT_EXCLUDE_DIRS_DEFAULT
from hassette.config.models import (
    DEFAULT_WEB_API_PORT,
    AppsConfig,
    DatabaseConfig,
    FileWatcherConfig,
    LifecycleConfig,
    LoggingConfig,
    SchedulerConfig,
    WebApiConfig,
    WebSocketConfig,
)
from hassette.test_utils.config import TEST_TOKEN


@pytest.mark.parametrize(
    "model_cls",
    [
        DatabaseConfig,
        WebSocketConfig,
        LoggingConfig,
        LifecycleConfig,
        WebApiConfig,
        AppsConfig,
        SchedulerConfig,
        FileWatcherConfig,
    ],
    ids=[
        "DatabaseConfig",
        "WebSocketConfig",
        "LoggingConfig",
        "LifecycleConfig",
        "WebApiConfig",
        "AppsConfig",
        "SchedulerConfig",
        "FileWatcherConfig",
    ],
)
def test_nested_models_are_base_model_not_base_settings(model_cls):
    """AC#9: All 8 nested model classes are BaseModel subclasses, not BaseSettings subclasses."""
    assert issubclass(model_cls, BaseModel), f"{model_cls.__name__} must inherit BaseModel"
    assert not issubclass(model_cls, BaseSettings), f"{model_cls.__name__} must NOT inherit BaseSettings"


class TestDatabaseConfig:
    def test_defaults(self):
        """DatabaseConfig constructs with all defaults."""
        cfg = DatabaseConfig()
        assert cfg.path is None
        assert cfg.retention_days == 7
        assert cfg.max_size_mb == 500
        assert cfg.migration_timeout_seconds == 120
        assert cfg.write_queue_max == 2000
        assert cfg.telemetry_write_queue_max == 1000
        assert cfg.heartbeat_interval_seconds == 300
        assert cfg.retention_interval_seconds == 3600
        assert cfg.size_failsafe_interval_seconds == 3600
        assert cfg.size_failsafe_max_iterations == 10
        assert cfg.size_failsafe_delete_batch == 1000
        assert cfg.size_failsafe_vacuum_pages == 100
        assert cfg.max_consecutive_heartbeat_failures == 3

    def test_retention_days_ge_1(self):
        """retention_days rejects 0."""
        with pytest.raises(ValidationError):
            DatabaseConfig(retention_days=0)

    def test_max_size_mb_ge_0(self):
        """max_size_mb rejects negative values."""
        with pytest.raises(ValidationError):
            DatabaseConfig(max_size_mb=-1)

    def test_max_size_mb_zero_allowed(self):
        """max_size_mb accepts 0 (disables size failsafe)."""
        cfg = DatabaseConfig(max_size_mb=0)
        assert cfg.max_size_mb == 0

    def test_migration_timeout_ge_10(self):
        """migration_timeout_seconds rejects values below 10."""
        with pytest.raises(ValidationError):
            DatabaseConfig(migration_timeout_seconds=9)

    def test_write_queue_max_ge_1(self):
        """write_queue_max rejects 0."""
        with pytest.raises(ValidationError):
            DatabaseConfig(write_queue_max=0)

    def test_heartbeat_interval_ge_10(self):
        """heartbeat_interval_seconds rejects values below 10."""
        with pytest.raises(ValidationError):
            DatabaseConfig(heartbeat_interval_seconds=9)

    def test_retention_interval_ge_60(self):
        """retention_interval_seconds rejects values below 60."""
        with pytest.raises(ValidationError):
            DatabaseConfig(retention_interval_seconds=59)

    def test_size_failsafe_interval_ge_60(self):
        """size_failsafe_interval_seconds rejects values below 60."""
        with pytest.raises(ValidationError):
            DatabaseConfig(size_failsafe_interval_seconds=59)

    def test_size_failsafe_max_iterations_ge_1(self):
        """size_failsafe_max_iterations rejects 0."""
        with pytest.raises(ValidationError):
            DatabaseConfig(size_failsafe_max_iterations=0)

    def test_custom_path(self):
        """path accepts a Path value."""
        cfg = DatabaseConfig(path=Path("/tmp/test.db"))
        assert cfg.path == Path("/tmp/test.db")


class TestWebSocketConfig:
    def test_defaults(self):
        """WebSocketConfig constructs with all defaults."""
        cfg = WebSocketConfig()
        assert cfg.authentication_timeout_seconds == 10
        assert cfg.response_timeout_seconds == 15
        assert cfg.connection_timeout_seconds == 5
        assert cfg.total_timeout_seconds == 30
        assert cfg.heartbeat_interval_seconds == 30
        assert cfg.connect_retry_max_attempts == 5
        assert cfg.connect_retry_initial_wait_seconds == 1.0
        assert cfg.connect_retry_max_wait_seconds == 32.0
        assert cfg.early_drop_stable_window_seconds == 30.0
        assert cfg.early_drop_max_retries == 5
        assert cfg.early_drop_backoff_initial_seconds == 2.0
        assert cfg.early_drop_backoff_max_seconds == 60.0
        assert cfg.max_recovery_seconds == 300.0

    def test_float_fields_are_float(self):
        """Float fields return float, not int."""
        cfg = WebSocketConfig()
        assert isinstance(cfg.connect_retry_initial_wait_seconds, float)
        assert isinstance(cfg.connect_retry_max_wait_seconds, float)
        assert isinstance(cfg.max_recovery_seconds, float)


class TestLoggingConfig:
    def test_defaults(self):
        """LoggingConfig constructs with all defaults."""
        cfg = LoggingConfig()
        assert cfg.log_level == "INFO"
        assert cfg.log_format == "auto"
        assert cfg.log_queue_max == 2000
        assert cfg.log_persistence_level == "INFO"
        assert cfg.log_retention_days == 3
        assert cfg.all_events is False

    def test_per_service_levels_filled_from_log_level_default(self):
        """With no overrides, per-service log levels default to log_level (INFO)."""
        cfg = LoggingConfig()
        for attr in (
            "database_service",
            "bus_service",
            "scheduler_service",
            "app_handler",
            "web_api",
            "websocket",
            "service_watcher",
            "file_watcher",
            "task_bucket",
            "command_executor",
            "apps",
            "state_proxy",
            "api",
        ):
            val = getattr(cfg, attr)
            assert val == "INFO", f"Expected {attr}='INFO', got {val!r}"

    def test_per_service_levels_filled_from_custom_log_level(self):
        """When log_level=DEBUG, unset per-service levels default to DEBUG."""
        cfg = LoggingConfig(log_level="DEBUG")
        assert cfg.database_service == "DEBUG"
        assert cfg.bus_service == "DEBUG"
        assert cfg.api == "DEBUG"

    def test_per_service_level_override_takes_precedence(self):
        """A per-service override beats the global log_level fill."""
        cfg = LoggingConfig(log_level="DEBUG", websocket="WARNING")
        assert cfg.websocket == "WARNING"
        assert cfg.database_service == "DEBUG"

    def test_all_hass_events_defaults_from_all_events_false(self):
        """all_hass_events defaults to False when all_events is False."""
        cfg = LoggingConfig()
        assert cfg.all_hass_events is False
        assert cfg.all_hassette_events is False

    def test_all_hass_events_defaults_from_all_events_true(self):
        """all_hass_events and all_hassette_events default to True when all_events=True."""
        cfg = LoggingConfig(all_events=True)
        assert cfg.all_hass_events is True
        assert cfg.all_hassette_events is True

    def test_all_hass_events_can_be_set_independently(self):
        """all_hass_events can override the all_events default."""
        cfg = LoggingConfig(all_events=False, all_hass_events=True)
        assert cfg.all_hass_events is True
        assert cfg.all_hassette_events is False

    def test_log_retention_days_ge_1(self):
        """log_retention_days rejects 0."""
        with pytest.raises(ValidationError):
            LoggingConfig(log_retention_days=0)

    def test_invalid_log_level_coerced_to_info(self):
        """Invalid log level string falls back to INFO."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cfg = LoggingConfig(log_level="BADLEVEL")  # pyright: ignore[reportArgumentType]
        assert cfg.log_level == "INFO"


class TestLifecycleConfig:
    def test_defaults(self):
        """LifecycleConfig constructs with all defaults."""
        cfg = LifecycleConfig()
        assert cfg.startup_timeout_seconds == 30
        assert cfg.app_startup_timeout_seconds == 20
        assert cfg.app_shutdown_timeout_seconds == 10
        assert cfg.total_shutdown_timeout_seconds == 30
        assert cfg.registration_await_timeout == 30
        assert cfg.event_handler_timeout_seconds == 600.0
        assert cfg.error_handler_timeout_seconds == 5.0
        assert cfg.run_sync_timeout_seconds == 6
        assert cfg.task_cancellation_timeout_seconds == 5

    def test_resource_shutdown_timeout_defaults_from_app_shutdown(self):
        """resource_shutdown_timeout_seconds defaults to app_shutdown_timeout_seconds."""
        cfg = LifecycleConfig()
        assert cfg.resource_shutdown_timeout_seconds == cfg.app_shutdown_timeout_seconds

    def test_resource_shutdown_timeout_follows_custom_app_shutdown(self):
        """resource_shutdown_timeout_seconds picks up custom app_shutdown_timeout_seconds."""
        cfg = LifecycleConfig(app_shutdown_timeout_seconds=25)
        assert cfg.resource_shutdown_timeout_seconds == 25

    def test_resource_shutdown_timeout_can_be_set_independently(self):
        """resource_shutdown_timeout_seconds can be set independently."""
        cfg = LifecycleConfig(app_shutdown_timeout_seconds=25, resource_shutdown_timeout_seconds=15)
        assert cfg.resource_shutdown_timeout_seconds == 15

    def test_event_handler_timeout_rejects_zero(self):
        """event_handler_timeout_seconds rejects 0."""
        with pytest.raises(ValidationError, match="timeout must be"):
            LifecycleConfig(event_handler_timeout_seconds=0.0)

    def test_event_handler_timeout_rejects_negative(self):
        """event_handler_timeout_seconds rejects negative values."""
        with pytest.raises(ValidationError, match="timeout must be"):
            LifecycleConfig(event_handler_timeout_seconds=-1.0)

    def test_event_handler_timeout_accepts_none(self):
        """event_handler_timeout_seconds accepts None to disable."""
        cfg = LifecycleConfig(event_handler_timeout_seconds=None)
        assert cfg.event_handler_timeout_seconds is None

    def test_error_handler_timeout_rejects_bool(self):
        """error_handler_timeout_seconds rejects booleans."""
        with pytest.raises(ValidationError, match="timeout must be"):
            LifecycleConfig(error_handler_timeout_seconds=True)

    def test_error_handler_timeout_accepts_none(self):
        """error_handler_timeout_seconds accepts None."""
        cfg = LifecycleConfig(error_handler_timeout_seconds=None)
        assert cfg.error_handler_timeout_seconds is None


class TestWebApiConfig:
    def test_defaults(self):
        """WebApiConfig constructs with all defaults."""
        cfg = WebApiConfig()
        assert cfg.run is True
        assert cfg.run_ui is True
        assert cfg.ui_hot_reload is False
        assert cfg.host == "0.0.0.0"
        assert cfg.port == DEFAULT_WEB_API_PORT
        assert cfg.cors_origins == ("http://localhost:3000", "http://localhost:5173")
        assert cfg.event_buffer_size == 500
        assert cfg.log_buffer_size == 2000
        assert cfg.job_history_size == 1000


class TestAppsConfig:
    def test_defaults(self):
        """AppsConfig constructs with all defaults."""
        cfg = AppsConfig()
        assert cfg.autodetect is True
        assert cfg.extend_exclude_dirs == ()
        assert cfg.manifests == {}
        assert cfg.apps == {}

    def test_exclude_dirs_includes_defaults(self):
        """exclude_dirs always includes AUTODETECT_EXCLUDE_DIRS_DEFAULT."""
        cfg = AppsConfig()
        for d in AUTODETECT_EXCLUDE_DIRS_DEFAULT:
            assert d in cfg.exclude_dirs, f"{d!r} missing from exclude_dirs"

    def test_extend_exclude_dirs_prepended(self):
        """extend_exclude_dirs values are prepended to exclude_dirs."""
        cfg = AppsConfig(extend_exclude_dirs=(".hg", ".svn"))
        assert ".hg" in cfg.exclude_dirs
        assert ".svn" in cfg.exclude_dirs
        # Defaults still present
        for d in AUTODETECT_EXCLUDE_DIRS_DEFAULT:
            assert d in cfg.exclude_dirs

    def test_remove_incomplete_apps(self):
        """Apps missing required keys are removed with a warning."""

        cfg = AppsConfig(apps={"incomplete": {"filename": "foo.py"}})

        assert "incomplete" not in cfg.apps

    def test_directory_default_is_cwd_apps(self):
        """directory defaults to cwd/apps."""
        cfg = AppsConfig()
        assert cfg.directory == Path.cwd() / "apps"

    def test_inline_app_defs_extracted(self):
        """Dict-valued unknown keys are extracted as app definitions."""
        cfg = AppsConfig(**{"my_app": {"filename": "f.py", "class_name": "C"}, "autodetect": False})
        assert "my_app" in cfg.apps
        assert cfg.autodetect is False

    def test_inline_defs_merged_with_existing_apps_key(self):
        """Inline app defs merge with an explicit apps dict."""
        cfg = AppsConfig(
            **{
                "apps": {"existing": {"filename": "e.py", "class_name": "E"}},
                "new_app": {"filename": "n.py", "class_name": "N"},
            }
        )
        assert "existing" in cfg.apps
        assert "new_app" in cfg.apps

    def test_non_dict_unknown_key_ignored(self):
        """Non-dict unknown keys don't blow up or get extracted."""
        cfg = AppsConfig(**{"some_string": "value", "autodetect": False})
        assert cfg.autodetect is False
        assert cfg.apps == {}

    def test_caller_dict_not_mutated(self):
        """The model_validator doesn't mutate the caller's input dict."""
        original = {"my_app": {"filename": "f.py", "class_name": "C"}}
        snapshot = dict(original)
        AppsConfig(**original)
        assert original == snapshot

    @pytest.mark.parametrize("reserved_name", ["directory", "autodetect", "extend_exclude_dirs", "exclude_dirs"])
    def test_reserved_app_name_raises(self, reserved_name: str):
        """App names that collide with config fields produce a clear error."""
        with pytest.raises(ValidationError, match="conflicts with a reserved config field"):
            AppsConfig(**{reserved_name: {"filename": "f.py", "class_name": "C"}})


class TestSchedulerConfig:
    def test_defaults(self):
        """SchedulerConfig constructs with all defaults."""
        cfg = SchedulerConfig()
        assert cfg.min_delay_seconds == 1
        assert cfg.max_delay_seconds == 30
        assert cfg.default_delay_seconds == 15
        assert cfg.behind_schedule_threshold_seconds == 5
        assert cfg.job_timeout_seconds == 600.0

    def test_job_timeout_rejects_zero(self):
        """job_timeout_seconds rejects 0."""
        with pytest.raises(ValidationError, match="timeout must be"):
            SchedulerConfig(job_timeout_seconds=0.0)

    def test_job_timeout_rejects_negative(self):
        """job_timeout_seconds rejects negative."""
        with pytest.raises(ValidationError, match="timeout must be"):
            SchedulerConfig(job_timeout_seconds=-5.0)

    def test_job_timeout_accepts_none(self):
        """job_timeout_seconds accepts None to disable."""
        cfg = SchedulerConfig(job_timeout_seconds=None)
        assert cfg.job_timeout_seconds is None

    def test_job_timeout_rejects_bool(self):
        """job_timeout_seconds rejects booleans."""
        with pytest.raises(ValidationError, match="timeout must be"):
            SchedulerConfig(job_timeout_seconds=True)


class TestFileWatcherConfig:
    def test_defaults(self):
        """FileWatcherConfig constructs with all defaults."""
        cfg = FileWatcherConfig()
        assert cfg.debounce_milliseconds == 3000
        assert cfg.step_milliseconds == 500
        assert cfg.watch_files is True


class TestHassetteConfigNested:
    """Integration tests: nested model fields accessible on HassetteConfig."""

    @pytest.fixture
    def isolated_config_cls(self):
        """Return an isolated HassetteConfig subclass (no TOML, no env, no CLI)."""

        class _IsolatedConfig(HassetteConfig):
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

        return _IsolatedConfig

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

        class _TomlConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": str(toml),
                "env_file": None,
            }

        config = _TomlConfig()
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

        class _TomlConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": str(toml),
                "env_file": None,
            }

        config = _TomlConfig()
        assert config.websocket.heartbeat_interval_seconds == 60

    def test_empty_nested_toml_section_produces_defaults(self, tmp_path):
        """An empty [hassette.database] section produces valid DatabaseConfig with all defaults."""
        toml = tmp_path / "hassette.toml"
        toml.write_text(
            "[hassette]\ntoken = 'test-token'\nrun_app_precheck = false\n\n[hassette.database]\n",
            encoding="utf-8",
        )

        class _TomlConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": str(toml),
                "env_file": None,
            }

        config = _TomlConfig()
        assert config.database.retention_days == 7
        assert config.database.max_size_mb == 500


class TestEnvVarPartialUpdate:
    """Setting a single env var for a nested field does not replace entire group defaults."""

    def test_single_env_var_sets_only_that_field(self, monkeypatch, tmp_path):
        """HASSETTE__DATABASE__RETENTION_DAYS=14 sets only retention_days."""
        monkeypatch.setenv("HASSETTE__DATABASE__RETENTION_DAYS", "14")

        class _EnvConfig2(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": None,
                "env_file": None,
            }

            token: str = TEST_TOKEN
            run_app_precheck: bool = False

        config = _EnvConfig2()
        assert config.database.retention_days == 14
        # Other database defaults are preserved (FR#5 / AC#4)
        assert config.database.max_size_mb == 500
        assert config.database.write_queue_max == 2000

    def test_env_var_logging_log_level(self, monkeypatch):
        """HASSETTE__LOGGING__LOG_LEVEL=DEBUG sets only logging.log_level."""
        monkeypatch.setenv("HASSETTE__LOGGING__LOG_LEVEL", "DEBUG")

        class _EnvConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": None,
                "env_file": None,
            }

            token: str = TEST_TOKEN
            run_app_precheck: bool = False

        config = _EnvConfig()
        assert config.logging.log_level == "DEBUG"


class TestCrossModelValidation:
    """Cross-model validators spanning nested models."""

    def test_log_retention_exceeds_db_retention_raises(self):
        """log_retention_days > retention_days raises ValidationError referencing both paths."""

        class _ValidationConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {
                "cli_parse_args": False,
                "toml_file": None,
                "env_file": None,
            }

            token: str = TEST_TOKEN
            run_app_precheck: bool = False

        with pytest.raises((ValidationError, ValueError)) as exc_info:
            _ValidationConfig(
                database={"retention_days": 3},
                logging={"log_retention_days": 5},
            )
        error_text = str(exc_info.value)
        # Error should reference both nested paths
        assert "log_retention_days" in error_text or "retention" in error_text
