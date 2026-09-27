"""Unit tests for the smaller nested config model classes in hassette.config.models.

Covers defaults, field constraints, computed defaults, and intra-model validators.
LoggingConfig and LifecycleConfig tests live in their own files (they appear here only in the
shared BaseModel-vs-BaseSettings check); HassetteConfig-level nested loading lives in
test_config_nested_loading.py.
"""

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings

from hassette.config.defaults import AUTODETECT_EXCLUDE_DIRS_DEFAULT
from hassette.config.models import (
    DEFAULT_WEB_API_PORT,
    AppsConfig,
    CliConfig,
    DatabaseConfig,
    FileWatcherConfig,
    LifecycleConfig,
    LoggingConfig,
    SchedulerConfig,
    WebApiConfig,
    WebSocketConfig,
)


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
        CliConfig,
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
        "CliConfig",
    ],
)
def test_nested_models_are_base_model_not_base_settings(model_cls):
    """All 8 nested model classes are BaseModel subclasses, not BaseSettings subclasses."""
    assert issubclass(model_cls, BaseModel), f"{model_cls.__name__} must inherit BaseModel"
    assert not issubclass(model_cls, BaseSettings), f"{model_cls.__name__} must NOT inherit BaseSettings"


class TestDatabaseConfig:
    def test_defaults(self):
        """DatabaseConfig constructs with all defaults."""
        cfg = DatabaseConfig()
        assert cfg.path is None
        assert cfg.retention_days == 7
        assert cfg.framework_retention_days == 1
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
        assert cfg.retention_delete_batch == 1000
        assert cfg.retention_max_batches_per_target == 100
        assert cfg.max_consecutive_heartbeat_failures == 3

    def test_retention_days_ge_1(self):
        """retention_days rejects 0."""
        with pytest.raises(ValidationError):
            DatabaseConfig(retention_days=0)

    def test_framework_retention_days_ge_1(self):
        """framework_retention_days rejects 0."""
        with pytest.raises(ValidationError):
            DatabaseConfig(framework_retention_days=0)

    def test_framework_retention_days_exceeds_retention_days_raises(self):
        """framework_retention_days > retention_days raises ValidationError naming both fields."""
        with pytest.raises(ValidationError) as exc_info:
            DatabaseConfig(framework_retention_days=5, retention_days=3)
        error_text = str(exc_info.value)
        assert "framework_retention_days (5)" in error_text
        assert "retention_days (3)" in error_text

    def test_framework_retention_days_equal_to_retention_days_is_valid(self):
        """framework_retention_days == retention_days is valid."""
        cfg = DatabaseConfig(framework_retention_days=3, retention_days=3)
        assert cfg.framework_retention_days == 3
        assert cfg.retention_days == 3

    def test_framework_retention_days_less_than_retention_days_is_valid(self):
        """framework_retention_days < retention_days is valid."""
        cfg = DatabaseConfig(framework_retention_days=1, retention_days=7)
        assert cfg.framework_retention_days == 1
        assert cfg.retention_days == 7

    def test_retention_delete_batch_ge_1(self):
        """retention_delete_batch rejects 0."""
        with pytest.raises(ValidationError):
            DatabaseConfig(retention_delete_batch=0)

    def test_retention_max_batches_per_target_ge_1(self):
        """retention_max_batches_per_target rejects 0."""
        with pytest.raises(ValidationError):
            DatabaseConfig(retention_max_batches_per_target=0)

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
        """Path accepts a Path value."""
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
        """Directory defaults to cwd/apps."""
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


class TestCliConfig:
    def test_defaults(self) -> None:
        """CliConfig constructs with all defaults."""
        cfg = CliConfig()
        assert cfg.server_url is None
        assert cfg.verify_ssl is True
        assert cfg.token_file is None
        assert cfg.auth_token is None
