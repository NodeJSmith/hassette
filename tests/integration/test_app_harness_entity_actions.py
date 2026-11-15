"""AppTestHarness records actions taken on entities the app fetched through its Api.

``RecordingApi.get_entity`` binds each entity to the recorder, as ``Api.get_entity`` binds it to the
app's ``Api``, so ``entity.turn_on()`` lands in ``api_recorder`` instead of the harness's unconnected Api.
"""

from hassette.app.app import App, AppSync
from hassette.app.app_config import AppConfig
from hassette.events import RawStateChangeEvent
from hassette.models.entities.light import LightEntity
from hassette.testing import AppTestHarness


class EntityActionConfig(AppConfig):
    """Minimal AppConfig for entity-action tests."""


class AsyncEntityApp(App[EntityActionConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change("sensor.trigger", handler=self.on_trigger, name="entity_trigger")

    async def on_trigger(self) -> None:
        light = await self.api.get_entity("light.kitchen", LightEntity)
        await light.turn_on()
        maybe = await self.api.get_entity_or_none("light.porch", LightEntity)
        assert maybe is not None
        await maybe.turn_off()


class SyncEntityApp(AppSync[EntityActionConfig]):
    def on_initialize_sync(self) -> None:
        self.bus.sync.on_state_change("sensor.trigger", handler=self.on_trigger, name="sync_entity_trigger")

    def on_trigger(self, event: RawStateChangeEvent) -> None:
        light = self.api.sync.get_entity("light.kitchen", LightEntity)
        light.sync.turn_on()
        maybe = self.api.sync.get_entity_or_none("light.porch", LightEntity)
        assert maybe is not None
        maybe.sync.turn_off()


async def test_entity_actions_recorded_from_async_app():
    async with AppTestHarness(AsyncEntityApp, config={"instance_name": "async_entity_app"}) as harness:
        await harness.set_states({"light.kitchen": "off", "light.porch": "on"})

        await harness.simulate_state_change("sensor.trigger", old_value="off", new_value="on")

        harness.api_recorder.assert_called(
            "call_service", domain="light", service="turn_on", target={"entity_id": "light.kitchen"}
        )
        harness.api_recorder.assert_called(
            "call_service", domain="light", service="turn_off", target={"entity_id": "light.porch"}
        )


async def test_entity_actions_recorded_from_sync_app():
    async with AppTestHarness(SyncEntityApp, config={"instance_name": "sync_entity_app"}) as harness:
        await harness.set_states({"light.kitchen": "off", "light.porch": "on"})

        await harness.simulate_state_change("sensor.trigger", old_value="off", new_value="on")

        harness.api_recorder.assert_called(
            "call_service", domain="light", service="turn_on", target={"entity_id": "light.kitchen"}
        )
        harness.api_recorder.assert_called(
            "call_service", domain="light", service="turn_off", target={"entity_id": "light.porch"}
        )
