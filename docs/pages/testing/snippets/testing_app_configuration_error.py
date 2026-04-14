import pytest

from hassette.test_utils import AppConfigurationError, AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_missing_config_raises():
    with pytest.raises(AppConfigurationError) as exc_info:
        async with AppTestHarness(MotionLights, config={}) as harness:
            pass

    # The error message includes the field name and validation failure reason
    print(exc_info.value)
    # AppConfigurationError for MotionLights: 1 validation error — field 'motion_entity': Field required
