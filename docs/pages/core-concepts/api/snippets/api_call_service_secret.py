from pydantic import SecretStr

from hassette import App, AppConfig


class FrontDoorConfig(AppConfig):
    lock_code: SecretStr


class FrontDoorApp(App[FrontDoorConfig]):
    async def on_initialize(self):
        await self.api.call_service(
            "lock",
            "unlock",
            target={"entity_id": "lock.front_door"},
            code=self.app_config.lock_code,
        )
