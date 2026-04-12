# --8<-- [start:imports]
from whenever import TimeDelta, ZonedDateTime
# --8<-- [end:imports]

from hassette import App, AppConfig


class DateApp(App[AppConfig]):
    async def on_initialize(self):
        last_seen: ZonedDateTime = self.now()
        # --8<-- [start:usage]
        next_run = self.now().add(hours=2)  # 2 hours from now
        elapsed = self.now() - last_seen  # returns a TimeDelta
        # --8<-- [end:usage]
