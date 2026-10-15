"""run_in accepts minutes=/hours= alongside its positional seconds delay."""

from typing import Any

import pytest
from whenever import SYSTEM_TZ, Instant

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.testing import AppTestHarness

FROZEN = Instant.from_utc(2026, 4, 7, 6, 0)


class _RunInApp(App[AppConfig]):
    """App with a no-op task the tests schedule directly."""

    fire_count: int = 0

    async def task(self) -> None:
        self.fire_count += 1


@pytest.mark.parametrize(
    ("args", "kwargs", "expected_seconds"),
    [
        ((30,), {}, 30),
        ((), {"delay": 30}, 30),
        ((), {"minutes": 5}, 300),
        ((), {"hours": 1, "minutes": 30}, 5400),
        ((), {"minutes": 1, "delay": 30}, 90),
        ((15,), {"hours": 1}, 3615),
    ],
)
async def test_run_in_unit_keywords_schedule_expected_delay(
    args: tuple[Any, ...], kwargs: dict[str, Any], expected_seconds: int
) -> None:
    """The delay components add up, and the job fires exactly when the total elapses."""
    async with AppTestHarness(_RunInApp, config={}) as harness:
        harness.freeze_time(FROZEN)
        job = await harness.app.scheduler.run_in(harness.app.task, *args, name="unit_job", **kwargs)

        assert job.next_run == FROZEN.to_tz(SYSTEM_TZ).add(seconds=expected_seconds)

        harness.advance_time(seconds=expected_seconds - 1)
        assert await harness.trigger_due_jobs() == 0
        assert harness.app.fire_count == 0

        harness.advance_time(seconds=1)
        assert await harness.trigger_due_jobs() == 1
        assert harness.app.fire_count == 1


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [
        ((), {}),
        ((0,), {}),
        ((-5,), {}),
        ((), {"minutes": 1, "delay": -60}),
        ((), {"hours": -1}),
    ],
)
async def test_run_in_non_positive_total_raises(args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    """No duration, or a total of zero or less, raises ValueError instead of scheduling."""
    async with AppTestHarness(_RunInApp, config={}) as harness:
        with pytest.raises(ValueError, match="delay must be positive"):
            await harness.app.scheduler.run_in(harness.app.task, *args, name="bad_job", **kwargs)
        assert not any(j.name == "bad_job" for j in harness.app.scheduler.list_jobs())
