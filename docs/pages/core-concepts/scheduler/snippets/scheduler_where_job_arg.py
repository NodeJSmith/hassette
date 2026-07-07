from hassette import App, AppConfig
from hassette.scheduler import ScheduledJob


class TemperatureApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:where_job]
        await self.scheduler.run_every(
            self.check_entity,
            minutes=5,
            name="entity_check",
            kwargs={"entity_id": "sensor.temperature"},
            where=self.entity_enabled,
        )
        # --8<-- [end:where_job]

    def entity_enabled(self, job: ScheduledJob) -> bool:
        return job.kwargs["entity_id"] != "sensor.disabled"

    async def check_entity(self, entity_id: str):
        pass
