"""Unit tests for LifecycleConfig in hassette.config.models."""

import os

import pytest
from pydantic import ValidationError

from hassette.config.models import FOUNDATION_SHUTDOWN_BUDGET_SECONDS, LifecycleConfig


class TestLifecycleConfig:
    def test_defaults(self):
        """LifecycleConfig constructs with all defaults."""
        cfg = LifecycleConfig()
        assert cfg.startup_timeout_seconds == 30
        assert cfg.app_startup_timeout_seconds == 20
        assert cfg.shutdown_timeout_seconds == 10
        assert cfg.total_shutdown_timeout_seconds == 45
        assert cfg.event_handler_timeout_seconds == 600.0
        assert cfg.error_handler_timeout_seconds == 5.0
        assert cfg.run_sync_timeout_seconds == 6
        assert cfg.task_cancellation_timeout_seconds == 5
        assert cfg.sync_executor_max_workers == min(32, (os.cpu_count() or 1) + 4)
        assert cfg.sync_executor_saturation_warn_threshold == 0.75
        assert cfg.sync_executor_saturation_warn_rate_limit_seconds == 30.0
        assert cfg.command_executor_capacity_warn_threshold == 0.75
        assert cfg.command_executor_capacity_warn_rate_limit_seconds == 30.0

    def test_total_shutdown_timeout_must_exceed_the_foundation_budget(self):
        """total_shutdown_timeout_seconds at or below the foundation stage's budget leaves no stop stage."""
        with pytest.raises(ValidationError, match="total_shutdown_timeout_seconds"):
            LifecycleConfig(total_shutdown_timeout_seconds=FOUNDATION_SHUTDOWN_BUDGET_SECONDS)

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

    def test_sync_executor_max_workers_default(self) -> None:
        """sync_executor_max_workers defaults to min(32, cpu_count+4)."""
        cfg = LifecycleConfig()
        expected = min(32, (os.cpu_count() or 1) + 4)
        assert cfg.sync_executor_max_workers == expected

    def test_sync_executor_saturation_warn_threshold_custom(self) -> None:
        """sync_executor_saturation_warn_threshold accepts a custom value in [0, 1]."""
        cfg = LifecycleConfig(sync_executor_saturation_warn_threshold=0.6)
        assert cfg.sync_executor_saturation_warn_threshold == 0.6

    def test_sync_executor_saturation_warn_threshold_rejects_out_of_range(self) -> None:
        """sync_executor_saturation_warn_threshold rejects values outside [0, 1]."""
        with pytest.raises(ValidationError):
            LifecycleConfig(sync_executor_saturation_warn_threshold=1.1)
        with pytest.raises(ValidationError):
            LifecycleConfig(sync_executor_saturation_warn_threshold=-0.1)

    def test_sync_executor_saturation_warn_rate_limit_rejects_non_positive(self) -> None:
        """sync_executor_saturation_warn_rate_limit_seconds rejects zero and negative values."""
        with pytest.raises(ValidationError):
            LifecycleConfig(sync_executor_saturation_warn_rate_limit_seconds=0.0)

    def test_command_executor_capacity_warn_threshold_custom(self) -> None:
        """command_executor_capacity_warn_threshold accepts a custom value in [0, 1]."""
        cfg = LifecycleConfig(command_executor_capacity_warn_threshold=0.9)
        assert cfg.command_executor_capacity_warn_threshold == 0.9

    def test_command_executor_capacity_warn_threshold_rejects_out_of_range(self) -> None:
        """command_executor_capacity_warn_threshold rejects values outside [0, 1]."""
        with pytest.raises(ValidationError):
            LifecycleConfig(command_executor_capacity_warn_threshold=1.1)

    def test_command_executor_capacity_warn_rate_limit_rejects_non_positive(self) -> None:
        """command_executor_capacity_warn_rate_limit_seconds rejects zero and negative values."""
        with pytest.raises(ValidationError):
            LifecycleConfig(command_executor_capacity_warn_rate_limit_seconds=0.0)

    def test_sync_and_command_warn_thresholds_are_independent(self) -> None:
        """sync_executor and command_executor warning thresholds can diverge (#1041)."""
        cfg = LifecycleConfig(
            sync_executor_saturation_warn_threshold=0.5,
            command_executor_capacity_warn_threshold=0.9,
        )
        assert cfg.sync_executor_saturation_warn_threshold == 0.5
        assert cfg.command_executor_capacity_warn_threshold == 0.9
