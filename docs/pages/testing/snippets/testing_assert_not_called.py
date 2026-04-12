from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_assert_not_called():
    async with AppTestHarness(MotionLights, config={}) as harness:
        harness.api_recorder.assert_not_called("call_service")
