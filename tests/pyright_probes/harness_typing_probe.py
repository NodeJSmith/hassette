"""Pyright probe proving AppTestHarness preserves the concrete app type."""

# ruff: noqa
# pyright: basic

from typing import assert_type

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.test_utils.app_harness import AppTestHarness


class ProbeConfig(AppConfig):
    pass


class ProbeApp(App[ProbeConfig]):
    probe_value: int


async def probe_harness_type() -> None:
    harness = AppTestHarness(ProbeApp)
    assert_type(harness, AppTestHarness[ProbeApp])

    async with harness as active:
        assert_type(active, AppTestHarness[ProbeApp])
        assert_type(active.app, ProbeApp)
        active.app.probe_value
