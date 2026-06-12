from hassette import App, AppConfig
from hassette.models.helpers import CreateInputBooleanParams, InputBooleanRecord


class VacationModeApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        record: InputBooleanRecord = await self.api.create_input_boolean(
            CreateInputBooleanParams(name="vacation_mode", initial=False)
        )
        self.logger.info("Provisioned vacation_mode helper: %s", record.id)
