from hassette.testing import AppTestHarness

from my_apps.door_log import DoorLog


async def test_door_log_records_the_triggering_event():
    async with AppTestHarness(DoorLog, config={"door_entity": "binary_sensor.front_door"}) as harness:
        event = await harness.simulate_state_change(
            "binary_sensor.front_door",
            old_value="off",
            new_value="on",
        )

        # Assert the behavior first: the app wrote a log entry.
        assert len(harness.app.entries) == 1

        # Then use the returned event to check the entry came from this change,
        # not from an event fired during app startup.
        assert harness.app.entries[0].context_id == event.payload.context.id
