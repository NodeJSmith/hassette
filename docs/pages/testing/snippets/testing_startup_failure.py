import logging

import pytest

from hassette.app import App, AppConfig
from hassette.testing import AppTestHarness


class GarageDoorConfig(AppConfig):
    pass


class GarageDoor(App[GarageDoorConfig]):
    async def on_initialize(self):
        raise RuntimeError("cover.garage_door is not configured")


async def test_initialize_failure_times_out(caplog):
    caplog.set_level(logging.ERROR)

    with pytest.raises(TimeoutError):
        async with AppTestHarness(
            GarageDoor, config={"instance_name": "garage_door"}
        ):
            pass

    # The exception raised in on_initialize appears in the log output
    assert "cover.garage_door is not configured" in caplog.text
