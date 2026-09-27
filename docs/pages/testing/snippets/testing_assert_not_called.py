from hassette.testing import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_assert_not_called():
    async with AppTestHarness(
        MotionLights,
        config={"motion_entity": "binary_sensor.motion", "light_entity": "light.kitchen"},
    ) as harness:
        harness.api_recorder.assert_not_called("call_service")
