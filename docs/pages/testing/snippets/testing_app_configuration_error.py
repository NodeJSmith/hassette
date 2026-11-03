import pytest

from hassette.testing import AppConfigurationError, AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_missing_config_raises():
    with pytest.raises(AppConfigurationError) as exc_info:
        async with AppTestHarness(
            MotionLights, config={"instance_name": "motion_lights"}
        ) as harness:
            pass

    # The error message counts the failures and names the first failing field
    print(exc_info.value)
    # AppConfigurationError for MotionLights: 2 validation errors — field 'motion_entity': Field required
