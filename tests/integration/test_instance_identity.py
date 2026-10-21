"""An app's unique_name, logger names and owner_id all derive from its instance name (#3095)."""

from hassette import App, AppConfig
from hassette.testing import AppTestHarness


class PorchLightApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        pass


async def test_identity_derives_from_the_configured_name() -> None:
    async with AppTestHarness(PorchLightApp, config={"instance_name": "front_porch"}) as harness:
        app = harness.app
        assert app.unique_name == "front_porch"
        assert app.logger.name == "hassette.apps.front_porch"
        assert app.bus.logger.name == "hassette.apps.front_porch.Bus"
        assert app.scheduler.logger.name == "hassette.apps.front_porch.Scheduler"
        assert app.bus.owner_id == "front_porch"
        assert app.scheduler.owner_id == "front_porch"
