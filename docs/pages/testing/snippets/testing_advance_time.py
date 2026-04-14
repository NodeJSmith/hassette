from whenever import Instant

from hassette.test_utils import AppTestHarness

from my_apps.reminder import ReminderApp


async def test_advance_time_variants():
    async with AppTestHarness(ReminderApp, config={}) as harness:
        harness.freeze_time(Instant.from_utc(2024, 1, 15, 9, 0, 0))

        harness.advance_time(seconds=30)
        harness.advance_time(minutes=5)
        harness.advance_time(hours=1)
        harness.advance_time(hours=1, minutes=30)  # combined
