"""Manual Job Demo.

A minimal app with a single daily job, used to demonstrate the "Run Now"
button and the "manual" execution badge in screenshots. The job itself
just logs the current light states — something a user might realistically
want to trigger on demand outside its daily schedule.

Demo entities:
    - light.kitchen_lights
    - light.ceiling_lights
"""

from hassette import App, AppConfig


class ManualJobConfig(AppConfig):
    report_hour: int = 8
    report_minute: int = 0


class ManualJobApp(App[ManualJobConfig]):
    """Daily light status report — trigger manually anytime."""

    async def on_initialize(self) -> None:
        cfg = self.app_config
        await self.scheduler.run_daily(
            self.light_status_report,
            at=f"{cfg.report_hour:02d}:{cfg.report_minute:02d}",
            name="light_status_report",
            if_exists="skip",
        )

    async def light_status_report(self) -> None:
        """Log current state of all lights."""
        for entity_id, light in self.states.light.items():
            self.logger.info("%s: %s", entity_id, light.value)
