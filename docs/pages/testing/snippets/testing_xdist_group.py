import pytest
from whenever import Instant

from hassette.test_utils import AppTestHarness

from my_apps.reminder import ReminderApp


@pytest.mark.xdist_group("time_control")
async def test_reminder_fires_after_one_hour():
    async with AppTestHarness(ReminderApp, config={}) as harness:
        harness.freeze_time(Instant.from_utc(2024, 1, 15, 9, 0, 0))
        harness.advance_time(hours=1)
        count = await harness.trigger_due_jobs()
        assert count == 1
