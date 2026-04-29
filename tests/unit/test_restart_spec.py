"""Unit tests for RestartSpec frozen dataclass."""

import pytest

from hassette.resources.base import RestartSpec
from hassette.types.enums import RestartType


class TestRestartSpecDefaults:
    def test_restart_spec_defaults(self) -> None:
        """Verify all default field values match the design."""
        spec = RestartSpec()
        assert spec.restart_type is RestartType.TRANSIENT
        assert spec.non_retryable_error_names == ()
        assert spec.fatal_error_names == ()
        assert spec.backoff_base_seconds == 2.0
        assert spec.backoff_multiplier == 2.0
        assert spec.backoff_max_seconds == 60.0
        assert spec.budget_intensity == 5
        assert spec.budget_period_seconds == 300.0
        assert spec.startup_timeout_seconds == 30.0
        assert spec.cooldown_seconds == 300.0
        assert spec.max_cooldown_cycles == 0


class TestRestartSpecFrozen:
    def test_restart_spec_frozen(self) -> None:
        """Verify frozen dataclass raises on attribute assignment."""
        spec = RestartSpec()
        with pytest.raises((AttributeError, TypeError)):
            spec.budget_intensity = 10  # pyright: ignore[reportAttributeAccessIssue]


class TestRestartSpecCustomValues:
    def test_restart_spec_custom_values(self) -> None:
        """Verify custom field values are preserved."""
        spec = RestartSpec(
            restart_type=RestartType.PERMANENT,
            non_retryable_error_names=("ValueError", "KeyError"),
            fatal_error_names=("SystemExit",),
            backoff_base_seconds=5.0,
            backoff_multiplier=3.0,
            backoff_max_seconds=120.0,
            budget_intensity=10,
            budget_period_seconds=600.0,
            startup_timeout_seconds=60.0,
            cooldown_seconds=900.0,
            max_cooldown_cycles=3,
        )
        assert spec.restart_type is RestartType.PERMANENT
        assert spec.non_retryable_error_names == ("ValueError", "KeyError")
        assert spec.fatal_error_names == ("SystemExit",)
        assert spec.backoff_base_seconds == 5.0
        assert spec.backoff_multiplier == 3.0
        assert spec.backoff_max_seconds == 120.0
        assert spec.budget_intensity == 10
        assert spec.budget_period_seconds == 600.0
        assert spec.startup_timeout_seconds == 60.0
        assert spec.cooldown_seconds == 900.0
        assert spec.max_cooldown_cycles == 3
