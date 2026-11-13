from hassette import App, AppConfig
from hassette.models.helpers import (
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
