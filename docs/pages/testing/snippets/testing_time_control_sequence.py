from whenever import Instant

from hassette.test_utils import AppTestHarness

from my_apps.reminder import ReminderApp


async def test_reminder_fires_after_one_hour():
    async with AppTestHarness(ReminderApp, config={}) as harness:
        # 1. Freeze time at a known point
        start = Instant.from_utc(2024, 1, 15, 9, 0, 0)  # 2024-01-15 09:00 UTC
        harness.freeze_time(start)

        # 2. Schedule the job (app registers it in on_initialize, but you
        #    can also trigger registration logic via simulate_* here)

        # 3. Advance the frozen clock
        harness.advance_time(hours=1)

        # 4. Fire any jobs whose due time is now <= frozen clock
        count = await harness.trigger_due_jobs()
        assert count == 1

        # 5. Assert your app made the expected API call
        harness.api_recorder.assert_called("fire_event", event_type="reminder_fired")
