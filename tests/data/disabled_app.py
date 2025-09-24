from hassette import App, AppConfig


class MyAppUserConfig(AppConfig):
    test_entity: str = "input_button.test"


class DisabledApp(App[MyAppUserConfig]):
    async def initialize(self) -> None:
        await super().initialize()
