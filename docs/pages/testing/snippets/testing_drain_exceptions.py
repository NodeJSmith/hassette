from hassette.test_utils import AppTestHarness, DrainError, DrainFailure, DrainTimeout

from my_apps.motion_lights import MotionLights


async def test_drain_exception_handling():
    async with AppTestHarness(MotionLights, config={}) as harness:
        try:
            await harness.simulate_state_change(
                "binary_sensor.motion", old_value="off", new_value="on"
            )
        except DrainFailure:
            # Catch any drain failure with a single except clause.
            # Inspect the type to distinguish cause:
            raise


async def test_drain_specific_handling():
    async with AppTestHarness(MotionLights, config={}) as harness:
        try:
            await harness.simulate_state_change(
                "binary_sensor.motion", old_value="off", new_value="on"
            )
        except DrainError as e:
            # e.task_exceptions is a list of (task_name, exception) pairs
            raise
        except DrainTimeout:
            # diagnostic message includes pending task names and a debounce hint
            raise
