from hassette import D
from hassette.app import App, AppConfig
from hassette.test_utils import AppTestHarness


class AuditConfig(AppConfig):
    pass


class AuditApp(App[AuditConfig]):
    async def on_initialize(self):
        self.bus.on_call_service(domain="light", handler=self.on_light_service)

    async def on_light_service(self, domain: D.Domain):
        await self.api.call_service("notify", "log", message=f"Service called on {domain}")


async def test_typed_call_service_handler():
    async with AppTestHarness(AuditApp, config={}) as harness:
        await harness.simulate_call_service("light", "turn_on", entity_id="light.kitchen")
        harness.api_recorder.assert_called("call_service", domain="notify", service="log", message="Service called on light")
