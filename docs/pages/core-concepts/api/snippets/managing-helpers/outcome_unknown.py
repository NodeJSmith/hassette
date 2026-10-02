from hassette import App, AppConfig
from hassette.exceptions import OutcomeUnknownError
from hassette.models.helpers import (
    CreateInputBooleanParams,
    InputBooleanRecord,
)


class HelperRecoveryApp(App[AppConfig]):
    # --8<-- [start:recover]
    async def create_vacation_mode(self) -> InputBooleanRecord | None:
        params = CreateInputBooleanParams(name="vacation_mode")
        try:
            return await self.api.helpers.create(params)
        except OutcomeUnknownError:
            # The create may or may not have applied. Check before retrying.
            records = await self.api.helpers.list("input_boolean")
            for record in records:
                if record.id == "vacation_mode":
                    return record
            return None
    # --8<-- [end:recover]
