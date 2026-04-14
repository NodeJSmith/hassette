from whenever import Instant, ZonedDateTime

from hassette.test_utils import AppTestHarness

from my_apps.reminder import ReminderApp


async def test_freeze_time_variants():
    async with AppTestHarness(ReminderApp, config={}) as harness:
        # From a UTC instant (most portable)
        harness.freeze_time(Instant.from_utc(2024, 6, 1, 8, 0, 0))

        # From a ZonedDateTime (when local time matters)
        harness.freeze_time(ZonedDateTime(2024, 6, 1, 8, 0, 0, tz="America/Chicago"))
