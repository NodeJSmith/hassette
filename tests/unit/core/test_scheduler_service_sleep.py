"""Tests for SchedulerService sleep-time calculation and wake-on-kick behavior."""

import asyncio
from unittest.mock import patch

import pytest

import hassette.utils.date_utils as date_utils
from hassette.core.scheduler_service import MAX_SLEEP_SECONDS

from .conftest import make_scheduler_service

SOON_JOB_DELAY_SECONDS = 0.3


class TestCalculateSleepTime:
    def test_sleeps_exactly_until_soon_job(self) -> None:
        """A job due shortly after the loop pass is not floored to a minimum delay."""
        svc = make_scheduler_service()
        loop_pass_at = date_utils.now()

        with patch.object(date_utils, "now", return_value=loop_pass_at):
            sleep = svc.calculate_sleep_time(loop_pass_at.add(seconds=SOON_JOB_DELAY_SECONDS)).total("seconds")

        assert sleep == pytest.approx(SOON_JOB_DELAY_SECONDS)

    def test_overdue_job_sleeps_zero(self) -> None:
        """A job whose due time has passed yields a zero sleep, never negative."""
        svc = make_scheduler_service()

        sleep = svc.calculate_sleep_time(date_utils.now().subtract(seconds=5)).total("seconds")

        assert sleep == 0.0

    def test_far_future_job_capped(self) -> None:
        """A far-future job sleeps at most MAX_SLEEP_SECONDS."""
        svc = make_scheduler_service()

        sleep = svc.calculate_sleep_time(date_utils.now().add(hours=6)).total("seconds")

        assert sleep == MAX_SLEEP_SECONDS

    def test_empty_queue_sleeps_max(self) -> None:
        """With no queued jobs the loop sleeps MAX_SLEEP_SECONDS."""
        svc = make_scheduler_service()

        assert svc.calculate_sleep_time(None).total("seconds") == MAX_SLEEP_SECONDS


async def test_kick_wakes_idle_sleep_immediately() -> None:
    """kick() (fired by add_job) interrupts an idle MAX_SLEEP_SECONDS sleep."""
    svc = make_scheduler_service()

    sleep_task = asyncio.create_task(svc.sleep(None))
    await asyncio.sleep(0)  # let the task reach its wait before kicking
    svc.kick()

    await asyncio.wait_for(sleep_task, timeout=1)
