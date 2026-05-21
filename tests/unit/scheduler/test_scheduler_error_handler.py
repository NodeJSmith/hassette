"""Tests for Scheduler error handler registration (WP03)."""

from unittest.mock import MagicMock, patch

from hassette.scheduler.triggers import Every
from hassette.test_utils.config import TEST_SOURCE_LOCATION

from .conftest import make_scheduler, noop

PATCH_TARGET = "hassette.scheduler.scheduler.capture_registration_source"


async def handler_a(ctx) -> None:
    pass


async def handler_b(ctx) -> None:
    pass


class TestSchedulerOnErrorMethod:
    def test_on_error_stores_handler(self) -> None:
        """on_error() stores the handler on the Scheduler instance."""
        scheduler = make_scheduler()

        scheduler.on_error(handler_a)

        assert scheduler._error_handler is handler_a

    async def test_on_error_reset_on_initialize(self) -> None:
        """_error_handler is reset to None when on_initialize() is called."""
        scheduler = make_scheduler()
        # Stub mark_ready to avoid requiring full Resource infrastructure
        scheduler.mark_ready = MagicMock()
        scheduler.on_error(handler_a)
        assert scheduler._error_handler is handler_a

        # Simulate hot-reload: on_initialize resets state
        await scheduler.on_initialize()

        assert scheduler._error_handler is None

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
    def test_per_job_on_error_stored(self) -> None:
        """on_error= kwarg on schedule() is stored on the ScheduledJob."""
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()
            job = scheduler.schedule(noop, Every(hours=1), on_error=handler_a)
            assert job.error_handler is handler_a

    def test_job_error_handler_default_none(self) -> None:
        """error_handler defaults to None on ScheduledJob when not provided."""
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()
            job = scheduler.schedule(noop, Every(hours=1))
            assert job.error_handler is None

    def test_convenience_methods_pass_on_error(self) -> None:
        """All 7 convenience methods accept and pass on_error to ScheduledJob."""
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            job_run_in = scheduler.run_in(noop, delay=60, on_error=handler_a)
            assert job_run_in.error_handler is handler_a

            job_run_every = scheduler.run_every(noop, seconds=30, on_error=handler_a)
            assert job_run_every.error_handler is handler_a

            job_run_hourly = scheduler.run_hourly(noop, on_error=handler_a)
            assert job_run_hourly.error_handler is handler_a

            job_run_minutely = scheduler.run_minutely(noop, on_error=handler_a)
            assert job_run_minutely.error_handler is handler_a

            job_run_daily = scheduler.run_daily(noop, at="00:00", on_error=handler_a)
            assert job_run_daily.error_handler is handler_a

            job_run_cron = scheduler.run_cron(noop, "0 * * * *", on_error=handler_a)
            assert job_run_cron.error_handler is handler_a

            job_run_once = scheduler.run_once(noop, at="23:59", on_error=handler_a)
            assert job_run_once.error_handler is handler_a
