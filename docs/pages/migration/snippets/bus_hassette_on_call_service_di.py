from typing import Annotated, Any

from hassette import A, App, AppConfig, D


class MyConfig(AppConfig):
    button_entity: str = "input_button.test_button"


class MyApp(App[MyConfig]):
    async def on_initialize(self):
        # Handler with dependency injection
        sub = self.bus.on_call_service(
            service="press",
            handler=self.minimal_callback,
            where={"entity_id": self.app_config.button_entity},
        )
        self.logger.info("Subscribed: %s", sub)

    # Extract only what you need from the event
    async def minimal_callback(
        self,
        domain: D.Domain,
        service: Annotated[str, A.get_service],
        service_data: Annotated[Any, A.get_service_data],
    ) -> None:
        entity_id = service_data.get("entity_id", "unknown")
        self.logger.info("Button %s pressed (domain=%s, service=%s)", entity_id, domain, service)
        self.logger.info("Service data: %s", service_data)
