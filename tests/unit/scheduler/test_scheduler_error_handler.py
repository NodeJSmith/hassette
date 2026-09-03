"""Tests for Scheduler error handler registration."""

from unittest.mock import patch

import pytest

from hassette.scheduler.scheduler import Scheduler
from hassette.scheduler.triggers import Every
from tests.support.helpers import noop

from .conftest import make_scheduler


async def handler_a(ctx) -> None:
    pass


async def handler_b(ctx) -> None:
    pass


# All 7 convenience methods accept and pass on_error to ScheduledJob.
_ON_ERROR_CONVENIENCE_CALLS = [
    pytest.param(
        lambda s: s.run_in(noop, delay=60, on_error=handler_a, name="convenience_methods_pass_on_error_run_in"),
        id="run_in",
    ),
    pytest.param(
        lambda s: s.run_every(noop, seconds=30, on_error=handler_a, name="convenience_methods_pass_on_error_run_every"),
        id="run_every",
    ),
    pytest.param(
        lambda s: s.run_hourly(noop, on_error=handler_a, name="convenience_methods_pass_on_error_run_hourly"),
        id="run_hourly",
    ),
    pytest.param(
        lambda s: s.run_minutely(noop, on_error=handler_a, name="convenience_methods_pass_on_error_run_minutely"),
        id="run_minutely",
    ),
    pytest.param(
        lambda s: s.run_daily(noop, at="00:00", on_error=handler_a, name="convenience_methods_pass_on_error_run_daily"),
        id="run_daily",
    ),
    pytest.param(
        lambda s: s.run_cron(noop, "0 * * * *", on_error=handler_a, name="convenience_methods_pass_on_error_run_cron"),
        id="run_cron",
    ),
    pytest.param(
        lambda s: s.run_once(noop, at="23:59", on_error=handler_a, name="convenience_methods_pass_on_error_run_once"),
        id="run_once",
    ),
]


class TestSchedulerOnErrorMethod:
    def test_on_error_stores_handler(self) -> None:
        """on_error() stores the handler on the Scheduler instance."""
        scheduler = make_scheduler()

        scheduler.on_error(handler_a)

        assert scheduler._error_handler is handler_a

    async def test_on_error_reset_on_initialize(self) -> None:
        """_error_handler is reset to None when on_initialize() is called."""
        scheduler = make_scheduler()
        scheduler.on_error(handler_a)
        assert scheduler._error_handler is handler_a

        with patch("hassette.scheduler.scheduler.mark_ready") as mock_mark_ready:
            # Simulate hot-reload: on_initialize resets state
            await scheduler.on_initialize()

        assert scheduler._error_handler is None
        mock_mark_ready.assert_called_once_with(scheduler, reason="Scheduler initialized")

    def test_on_error_replaces_previous(self) -> None:
        """A second call to on_error() replaces the previous handler."""
        scheduler = make_scheduler()

        scheduler.on_error(handler_a)
        scheduler.on_error(handler_b)

        assert scheduler._error_handler is handler_b

    def test_error_handler_none_by_default(self) -> None:
        """_error_handler is None by default on a fresh Scheduler."""
        scheduler = make_scheduler()
        assert scheduler._error_handler is None


class TestPerJobOnError:
    async def test_per_job_on_error_stored(self, patched_scheduler: Scheduler) -> None:
        """on_error= kwarg on schedule() is stored on the ScheduledJob."""
        job = await patched_scheduler.schedule(
            noop, Every(hours=1), on_error=handler_a, name="per_job_on_error_stored_schedule"
        )
        assert job.error_handler is handler_a

    async def test_job_error_handler_default_none(self, patched_scheduler: Scheduler) -> None:
        """error_handler defaults to None on ScheduledJob when not provided."""
        job = await patched_scheduler.schedule(noop, Every(hours=1), name="job_error_handler_default_none_schedule")
        assert job.error_handler is None

    @pytest.mark.parametrize("call", _ON_ERROR_CONVENIENCE_CALLS)
    async def test_convenience_methods_pass_on_error(self, patched_scheduler: Scheduler, call) -> None:
        """Each of the 7 convenience methods accepts and passes on_error to ScheduledJob."""
        job = await call(patched_scheduler)
        assert job.error_handler is handler_a
