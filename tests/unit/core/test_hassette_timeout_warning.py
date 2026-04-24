"""Unit tests for startup WARNING when global timeouts are disabled."""

from unittest.mock import MagicMock

from hassette.core.core import Hassette


def _make_hassette_stub(
    scheduler_job_timeout: float | None = 600.0,
    event_handler_timeout: float | None = 600.0,
) -> Hassette:
    """Create a minimal Hassette stub with just enough to test on_initialize.

    Bypasses __init__ entirely and sets only the attributes needed for the
    timeout warning logic.
    """
    h = object.__new__(Hassette)
    config = MagicMock()
    config.scheduler_job_timeout_seconds = scheduler_job_timeout
    config.event_handler_timeout_seconds = event_handler_timeout
    h.config = config
    h.logger = MagicMock()
    return h


class TestStartupWarningWhenJobTimeoutNone:
    """WARNING logged for scheduler_job_timeout_seconds=None."""

    async def test_startup_warning_when_job_timeout_none(self) -> None:
        h = _make_hassette_stub(scheduler_job_timeout=None, event_handler_timeout=600.0)

        await h.on_initialize()

        h.logger.warning.assert_any_call(
            "%s is None — execution timeout enforcement is disabled globally — framework components are unprotected",
            "scheduler_job_timeout_seconds",
        )


class TestStartupWarningWhenHandlerTimeoutNone:
    """WARNING logged for event_handler_timeout_seconds=None."""

    async def test_startup_warning_when_handler_timeout_none(self) -> None:
        h = _make_hassette_stub(scheduler_job_timeout=600.0, event_handler_timeout=None)

        await h.on_initialize()

        h.logger.warning.assert_any_call(
            "%s is None — execution timeout enforcement is disabled globally — framework components are unprotected",
            "event_handler_timeout_seconds",
        )


class TestNoWarningWhenTimeoutsConfigured:
    """No WARNING when both have values."""

    async def test_no_warning_when_timeouts_configured(self) -> None:
        h = _make_hassette_stub(scheduler_job_timeout=600.0, event_handler_timeout=600.0)

        await h.on_initialize()

        h.logger.warning.assert_not_called()


class TestWarningFiresOncePerStartup:
    """WARNING fires once during on_initialize, not repeated."""

    async def test_warning_fires_once_per_startup(self) -> None:
        """Verify on_initialize emits exactly one warning per disabled field."""
        h = _make_hassette_stub(scheduler_job_timeout=None, event_handler_timeout=None)

        await h.on_initialize()

        warning_calls = h.logger.warning.call_args_list
        # Exactly two warnings: one for each disabled timeout
        assert len(warning_calls) == 2
        # Each call passes (format_string, field_name) — check the field_name arg
        field_names = [call[0][1] for call in warning_calls]
        assert "scheduler_job_timeout_seconds" in field_names
        assert "event_handler_timeout_seconds" in field_names
