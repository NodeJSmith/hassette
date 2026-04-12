# --8<-- [start:imports]
from whenever import TimeDelta, ZonedDateTime
# --8<-- [end:imports]

from hassette import App, AppConfig


class DateApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:usage]
        last_seen: ZonedDateTime = self.now()
        next_run = self.now().add(hours=2)  # 2 hours from now
        elapsed: TimeDelta = self.now() - last_seen
        # --8<-- [end:usage]
