"""Unit tests for LoggingConfig in hassette.config.models."""

import warnings

import pytest
from pydantic import ValidationError

from hassette.config.models import LoggingConfig


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

    def test_extra_loggers_defaults_to_empty_tuple(self):
        """extra_loggers defaults to an empty tuple — no extra loggers attached."""
        cfg = LoggingConfig()
        assert cfg.extra_loggers == ()

    def test_extra_loggers_accepts_names(self):
        """extra_loggers stores configured logger names as a tuple."""
        cfg = LoggingConfig(extra_loggers=["my_app.notify", "my_app.laundry"])
        assert cfg.extra_loggers == ("my_app.notify", "my_app.laundry")

    def test_extra_loggers_rejects_empty_string(self):
        """An empty logger name is rejected — it would resolve to the root logger."""
        with pytest.raises(ValidationError):
            LoggingConfig(extra_loggers=[""])

    def test_extra_loggers_rejects_whitespace_only_string(self):
        """A whitespace-only logger name is rejected for the same reason as an empty one."""
        with pytest.raises(ValidationError):
            LoggingConfig(extra_loggers=["   "])

    def test_extra_loggers_rejects_multiline_whitespace_only_string(self):
        """A multi-line whitespace-only name (e.g. from a TOML triple-quoted string) is rejected
        the same as a single-line one — the min_length/pattern constraint isn't line-scoped.
        """
        with pytest.raises(ValidationError):
            LoggingConfig(extra_loggers=["\n \n"])

    def test_extra_loggers_accepts_name_with_leading_newline(self):
        """A name with real content is accepted even if it also contains a leading newline —
        the pattern only requires at least one non-whitespace character somewhere.
        """
        cfg = LoggingConfig(extra_loggers=["\nmy_app.notify"])
        assert cfg.extra_loggers == ("\nmy_app.notify",)

    def test_extra_loggers_rejects_py_warnings(self):
        """py.warnings is already managed by Hassette's logging setup — reconfiguring its level
        via extra_loggers would silently break HassetteForgottenAwaitWarning capture.
        """
        with pytest.raises(ValidationError, match=r"py\.warnings"):
            LoggingConfig(extra_loggers=["py.warnings"])

    def test_extra_loggers_rejects_hassette(self):
        """The hassette logger itself is already managed and may not be re-adopted."""
        with pytest.raises(ValidationError, match="hassette"):
            LoggingConfig(extra_loggers=["hassette"])

    def test_extra_loggers_rejects_root(self):
        """logging.getLogger("root") is stdlib's special case for the actual process root
        logger (the same trap an empty name hits) — adopting it would clear the root logger's
        handlers and route every propagating logger in the process through Hassette's pipeline.
        """
        with pytest.raises(ValidationError, match="root"):
            LoggingConfig(extra_loggers=["root"])
