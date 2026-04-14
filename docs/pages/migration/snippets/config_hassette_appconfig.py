from pydantic import Field

from hassette import App, AppConfig


class MyAppConfig(AppConfig):
    entity: str = Field(..., description="The entity to monitor")
    brightness: int = Field(100, ge=0, le=255, description="Brightness level (0-255)")


class MyApp(App[MyAppConfig]):
    async def on_initialize(self):
        self.logger.info("app_manifest=%r", self.app_manifest)
        self.logger.info("app_config=%r", self.app_config)
        entity = self.app_config.entity
        self.logger.info("My configured entity is %r (type %s)", entity, type(entity))
        brightness = self.app_config.brightness
        self.logger.info("My configured brightness is %r (type %s)", brightness, type(brightness))

        # 2025-10-13 18:57:45.495 INFO hassette.MyApp.0.on_initialize:13 - self.app_manifest=<AppManifest MyApp (MyApp) - enabled=True file=my_app.py>
        # 2025-10-13 18:57:45.495 INFO hassette.MyApp.0.on_initialize:14 - self.app_config=MyAppConfig(instance_name='MyApp.0', log_level='INFO', entity='light.kitchen', brightness=200)
        # 2025-10-13 18:57:45.495 INFO hassette.MyApp.0.on_initialize:17 - My configured entity is 'light.kitchen' (type <class 'str'>)
        # 2025-10-13 18:57:45.495 INFO hassette.MyApp.0.on_initialize:19 - My configured brightness is 200 (type <class 'int'>)
