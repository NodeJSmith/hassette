from whenever import Instant

from hassette import D
from hassette.app import App, AppConfig
from hassette.testing import AppTestHarness


class TrashReminderConfig(AppConfig):
    pass


class TrashReminder(App[TrashReminderConfig]):
    async def on_initialize(self):
        await self.bus.on(
            topic="trash.reminder",
            handler=self.send_reminder,
            name="trash_reminder",
        )
        await self.scheduler.run_in(
            self.announce, minutes=5, name="trash_announce"
        )

    async def announce(self) -> None:
        await self.bus.emit("trash.reminder", "Take out the trash")

    async def send_reminder(self, message: D.EventData[str]) -> None:
        await self.api.call_service(
            "notify", "send_message", message=message
        )


async def test_job_event_reaches_handler():
    async with AppTestHarness(
        TrashReminder, config={"instance_name": "trash_reminder"}
    ) as harness:
        harness.freeze_time(Instant.now())
        # Run times round to the whole second; step one second past them.
        harness.advance_time(minutes=5, seconds=1)
        await harness.trigger_due_jobs()

        # The job emitted the event; its handler task may still be pending.
        await harness.drain_task_bucket(timeout=2.0)

        harness.api_recorder.assert_called(
            "call_service",
            domain="notify",
            service="send_message",
            message="Take out the trash",
        )
