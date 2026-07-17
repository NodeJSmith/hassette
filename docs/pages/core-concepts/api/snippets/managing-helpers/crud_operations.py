from hassette import App, AppConfig
from hassette.models.helpers import (
    CreateInputBooleanParams,
    InputBooleanRecord,
    UpdateInputBooleanParams,
)


class HelperCrudApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:list]
        records: list[InputBooleanRecord] = await self.api.helpers.list("input_boolean")
        for record in records:
            self.logger.debug("Found input_boolean: id=%s name=%s", record.id, record.name)
        # --8<-- [end:list]

        # --8<-- [start:update]
        await self.api.helpers.update(
            "vacation_mode",
            UpdateInputBooleanParams(icon="mdi:palm-tree"),
        )
        # --8<-- [end:update]

        # --8<-- [start:delete]
        await self.api.helpers.delete("input_boolean", "vacation_mode")
        # --8<-- [end:delete]

    # --8<-- [start:bootstrap]
    async def ensure_vacation_mode(self) -> InputBooleanRecord:
        for record in await self.api.helpers.list("input_boolean"):
            if record.id == "vacation_mode":
                return record
        return await self.api.helpers.create(
            CreateInputBooleanParams(name="vacation_mode", initial=False)
        )
    # --8<-- [end:bootstrap]
