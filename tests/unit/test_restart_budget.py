"""Unit tests for RestartBudget sliding-window tracker."""

from unittest.mock import patch

from hassette.core.service_watcher import RestartBudget


class TestRestartBudgetEmpty:
    def test_budget_empty_not_exhausted(self) -> None:
        """New budget with no restarts returns is_exhausted() == False."""
        budget = RestartBudget(intensity=5, period_seconds=300.0)
        assert budget.is_exhausted() is False


class TestRestartBudgetExhaustion:
    def test_budget_exhausted_at_intensity(self) -> None:
        """Record intensity restarts, verify is_exhausted() == True."""
        budget = RestartBudget(intensity=5, period_seconds=300.0)
        with patch("time.monotonic", return_value=0.0):
            for _ in range(5):
                budget.record_restart()
        with patch("time.monotonic", return_value=1.0):
            assert budget.is_exhausted() is True

    def test_budget_not_exhausted_below_intensity(self) -> None:
        """Record intensity - 1 restarts, verify is_exhausted() == False."""
        budget = RestartBudget(intensity=5, period_seconds=300.0)
        with patch("time.monotonic", return_value=0.0):
            for _ in range(4):
                budget.record_restart()
        with patch("time.monotonic", return_value=1.0):
            assert budget.is_exhausted() is False


class TestRestartBudgetEviction:
    def test_budget_evicts_expired_timestamps(self) -> None:
        """Record restarts, advance time past window, verify old entries evicted."""
        budget = RestartBudget(intensity=5, period_seconds=300.0)
        with patch("time.monotonic", return_value=0.0):
            for _ in range(5):
                budget.record_restart()
        # Advance past the window (0.0 + 300.0 = 300.0; use > 300.0)
        with patch("time.monotonic", return_value=301.0):
            assert budget.is_exhausted() is False
            assert len(budget._timestamps) == 0

    def test_budget_boundary_timestamp(self) -> None:
        """Record restart exactly at the window boundary, verify correct eviction behavior.

        A timestamp at exactly (now - period) should be evicted since the condition
        is strictly > (not >=). A timestamp just inside the window should be kept.
        """
        budget = RestartBudget(intensity=1, period_seconds=300.0)
        # Record at t=0
        with patch("time.monotonic", return_value=0.0):
            budget.record_restart()

        # At t=300.0, cutoff = 300.0 - 300.0 = 0.0; t=0.0 is NOT > 0.0, so evicted
        with patch("time.monotonic", return_value=300.0):
            assert budget.is_exhausted() is False
            assert len(budget._timestamps) == 0

    def test_budget_mixed_expired_and_current(self) -> None:
        """Some timestamps expired, some current — verify only current count."""
        budget = RestartBudget(intensity=5, period_seconds=300.0)
        # Record 3 restarts in the past (will expire)
        with patch("time.monotonic", return_value=0.0):
            for _ in range(3):
                budget.record_restart()
        # Record 2 restarts just within the window
        with patch("time.monotonic", return_value=150.0):
            for _ in range(2):
                budget.record_restart()
        # At t=350.0, cutoff = 350.0 - 300.0 = 50.0
        # t=0.0 entries are NOT > 50.0 → evicted
        # t=150.0 entries ARE > 50.0 → retained
        with patch("time.monotonic", return_value=350.0):
            assert budget.is_exhausted() is False
            assert len(budget._timestamps) == 2


class TestRestartBudgetReset:
    def test_budget_reset_clears_all(self) -> None:
        """Record restarts, call reset(), verify is_exhausted() == False."""
        budget = RestartBudget(intensity=5, period_seconds=300.0)
        with patch("time.monotonic", return_value=0.0):
            for _ in range(5):
                budget.record_restart()
        with patch("time.monotonic", return_value=1.0):
            assert budget.is_exhausted() is True
        budget.reset()
        with patch("time.monotonic", return_value=1.0):
            assert budget.is_exhausted() is False
