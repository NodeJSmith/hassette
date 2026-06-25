from hassette import App, AppConfig


class MyAppUserConfig(AppConfig):
    test_entity: str = "input_button.test"


class NoAutostartApp(App[MyAppUserConfig]): ...
