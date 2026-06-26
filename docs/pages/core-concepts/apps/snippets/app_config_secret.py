from pydantic import SecretStr

from hassette import App, AppConfig


class MyAppConfig(AppConfig):
    # Declared SecretStr -> masked in the dashboard automatically.
    api_key: SecretStr

    # A plain str is never masked, even with a sensitive-looking name.
    public_token: str = "anon"


class MyApp(App[MyAppConfig]):
    async def on_initialize(self) -> None:
        # Unwrap with get_secret_value() to use the real value in code.
        secret = self.app_config.api_key.get_secret_value()
        self.logger.info("api key has %d chars", len(secret))
