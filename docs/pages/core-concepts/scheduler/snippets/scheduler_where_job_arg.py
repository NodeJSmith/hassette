from hassette import App, AppConfig
from hassette.scheduler import Job


class TemperatureApp(App[AppConfig]):
    async def on_initialize(self):
        await self.scheduler.run_every(
            self.check_entity,
            minutes=5,
            name="entity_check",
            kwargs={"entity_id": "sensor.temperature"},
            where=self.entity_enabled,
        )

    def entity_enabled(self, job: Job) -> bool:
        return job.kwargs["entity_id"] != "sensor.disabled"

    async def check_entity(self, entity_id: str):
        pass
