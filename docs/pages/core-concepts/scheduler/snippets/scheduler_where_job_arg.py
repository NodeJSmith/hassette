from hassette import App, AppConfig


class TemperatureApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:where_job]
        await self.scheduler.run_every(
            self.check_entity,
            minutes=5,
            name="entity_check",
            kwargs={"entity_id": "sensor.temperature"},
            where=lambda job: job.kwargs["entity_id"] != "sensor.disabled",
        )
        # --8<-- [end:where_job]

    async def check_entity(self, entity_id: str):
        pass
