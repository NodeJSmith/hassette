from hassette import App, AppConfig
from hassette.models.helpers import (
    CreateInputBooleanParams,
    InputBooleanRecord,
)


class VacationApp(App[AppConfig]):
    vacation_mode: InputBooleanRecord

    async def on_initialize(self) -> None:
        self.vacation_mode = await self.ensure_vacation_mode()

    async def ensure_vacation_mode(self) -> InputBooleanRecord:
        for record in await self.api.helpers.list("input_boolean"):
            if record.id == "vacation_mode":
                return record
        return await self.api.helpers.create(
            CreateInputBooleanParams(name="vacation_mode", initial=False)
        )
