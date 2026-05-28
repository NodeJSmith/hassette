from typing import Literal

from whenever import ZonedDateTime

from hassette import App, AppConfig


# --8<-- [start:trigger_class]
class SolarPollTrigger:
    """Polls on a fixed interval for use with elevation-based logic in the callback."""

    def __init__(self, check_every: int = 60):
        self.check_every = check_every

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        return current_time.add(seconds=self.check_every)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        return current_time.add(seconds=self.check_every)

    def trigger_label(self) -> str:
        return f"solar_poll (every {self.check_every}s)"

    def trigger_detail(self) -> str | None:
        return f"every {self.check_every}s"

    def trigger_db_type(self) -> Literal["interval", "cron", "once", "after", "custom"]:
        return "custom"

    def trigger_id(self) -> str:
        return f"solar_poll:{self.check_every}"
# --8<-- [end:trigger_class]


class SolarApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:trigger_usage]
        self.scheduler.schedule(self.check_sun_elevation, SolarPollTrigger(check_every=30))
        # --8<-- [end:trigger_usage]

    async def check_sun_elevation(self) -> None: ...
