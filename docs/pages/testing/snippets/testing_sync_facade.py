from hassette.test_utils import AppTestHarness

from my_apps.sync_app import SyncApp


async def test_sync_facade_recording():
    async with AppTestHarness(SyncApp, config={}) as harness:
        await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")

        # Your app calls: self.api.sync.turn_on("light.kitchen", domain="light")
        harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen", domain="light")
