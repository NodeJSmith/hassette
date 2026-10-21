"""Behavioral smoke test for ``hassette.testing`` against the installed wheel.

Runs inside the ``wheel_smoke`` nox session's venv, with only the built wheels installed
and no source checkout on ``sys.path`` (invoke with ``python -I``). Import checks alone miss
a missing runtime dependency, package-data file, or construction failure inside the wheel,
so this script drives a real ``AppTestHarness`` end to end: seed a state, simulate an
event, and assert on the recorded API call.

Each step is named; a failure prints ``wheel smoke failed at step '<name>'`` with the
traceback and exits 1.

Usage:
    python -I tools/release/wheel_smoke_harness.py
"""

import asyncio
import contextlib
import sys
import tempfile
import traceback
from collections.abc import Iterator

import hassette.testing
from hassette.app import App, AppConfig
from hassette.testing import AppTestHarness, make_test_config


class SmokeStepError(Exception):
    """A named smoke step failed; the original exception is chained as ``__cause__``."""

    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


class SmokeConfig(AppConfig):
    motion_entity: str
    light_entity: str


class SmokeApp(App[SmokeConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            self.app_config.motion_entity,
            changed_to="on",
            handler=self.on_motion,
            name="smoke_motion",
        )

    async def on_motion(self) -> None:
        await self.api.turn_on(self.app_config.light_entity)


@contextlib.contextmanager
def step(name: str) -> Iterator[None]:
    print(f"wheel smoke: {name}")
    try:
        yield
    except Exception as exc:
        raise SmokeStepError(name) from exc


async def run_harness() -> None:
    with step("resolve every hassette.testing.__all__ symbol"):
        for symbol in hassette.testing.__all__:
            getattr(hassette.testing, symbol)

    with tempfile.TemporaryDirectory(prefix="hassette-wheel-smoke-") as data_dir:
        with step("build hermetic test config"):
            make_test_config(data_dir=data_dir)

        config = {
            "instance_name": "smoke_app",
            "motion_entity": "binary_sensor.motion",
            "light_entity": "light.kitchen",
        }
        with step("enter AppTestHarness"):
            harness_cm = AppTestHarness(SmokeApp, config=config)
            harness = await harness_cm.__aenter__()

        try:
            with step("seed state with set_state"):
                await harness.set_state("binary_sensor.motion", "off")

            with step("simulate state change event"):
                await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")

            with step("assert api_recorder recorded turn_on"):
                harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")
        finally:
            with step("exit AppTestHarness"):
                await harness_cm.__aexit__(None, None, None)


def main() -> int:
    try:
        asyncio.run(run_harness())
    except SmokeStepError as exc:
        print(f"wheel smoke failed at step {exc.step!r}:", file=sys.stderr)
        traceback.print_exception(exc.__cause__, file=sys.stderr)
        return 1
    print("wheel smoke: all steps passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
