import asyncio
import contextlib
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, cast
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from whenever import SystemDateTime, TimeDelta

from hassette.core.core import Hassette, HassetteConfig
from hassette.core.scheduler import CronTrigger, IntervalTrigger, Scheduler, triggers
from hassette.core.scheduler.scheduler import _Scheduler

TZ = ZoneInfo("America/Chicago")


class MockHassette:
    task: asyncio.Task
    _loop: asyncio.AbstractEventLoop
    _thread_pool: ThreadPoolExecutor

    def __init__(self, test_config: "HassetteConfig"):
        self._scheduler = _Scheduler(cast("Hassette", self))
        self.scheduler = Scheduler(cast("Hassette", self), self._scheduler)

    async def send_event(self, topic: str, event: object) -> None:
        """Mock method to send an event to the bus."""
        pass

    def create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        return asyncio.create_task(coro)


@pytest.fixture
async def mock_scheduler(test_config: "HassetteConfig"):
    hassette = MockHassette(test_config)
    hassette._loop = asyncio.get_running_loop()
    hassette._thread_pool = ThreadPoolExecutor()
    previous_instance = Hassette._instance
    Hassette._instance = cast("Hassette", hassette)
    hassette.task = asyncio.create_task(hassette._scheduler.run_forever())
    await asyncio.sleep(0)  # Allow the task to start

    hassette._scheduler.max_delay = 1
    yield hassette.scheduler

    hassette.task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await hassette.task
    hassette._thread_pool.shutdown(wait=True)
    Hassette._instance = previous_instance


async def test_interval_trigger_catchup() -> None:
    # start 30s in the past, interval 10s, now=00:01:30 → next should be 00:01:40

    fake_now = SystemDateTime.from_py_datetime(datetime(2025, 8, 18, 0, 1, 30, tzinfo=TZ))  # "2025-08-18T00:01:30")
    with patch.object(triggers, "now", lambda: fake_now):
        trig = IntervalTrigger(TimeDelta(seconds=10), start=SystemDateTime(2025, 8, 18, 0, 1, 0))
        nxt = trig.next_run_time()
        assert nxt.format_common_iso() == "2025-08-18T00:01:40-05:00"


async def test_cron_trigger_catchup() -> None:
    fake_now = SystemDateTime.from_py_datetime(datetime(2025, 8, 18, 0, 1, 30, tzinfo=TZ))  # "2025-08-18T00:01:30")
    with patch.object(triggers, "now", lambda: fake_now):
        trig = CronTrigger.from_arguments(
            second="*/10", minute="*", hour="*", start=SystemDateTime(2025, 8, 18, 0, 1, 0)
        )
        nxt = trig.next_run_time()
        assert nxt.format_common_iso() == "2025-08-18T00:01:40-05:00"


async def test_run_cron_rejects_invalid(mock_scheduler: Scheduler) -> None:
    with pytest.raises(ValueError, match="Invalid cron expression"):
        mock_scheduler.run_cron(lambda: None, second="nope")


async def test_run_cron_accepts_valid(mock_scheduler: Scheduler) -> None:
    # “every 5 seconds” (fields: sec min hour dom mon dow year)
    job = mock_scheduler.run_cron(lambda: None, second="1", start=SystemDateTime(2025, 8, 18, 0, 0, 0))
    await asyncio.sleep(0)  # allow scheduling to complete
    job.cancel()


async def test_cron_trigger_seconds(hassette_logging: Hassette):  # noqa
    start_time = SystemDateTime(2025, 8, 18, 0, 0, 0)

    trig = CronTrigger.from_arguments(second="*/1", start=start_time)
    assert trig.cron_expression == "0 0 * * * */1"

    trig_next_time = trig.cron_iter.get_next()

    delta = SystemDateTime.from_py_datetime(trig_next_time) - start_time

    assert delta.in_seconds() == 1.0, f"Delta was {delta.in_seconds()} seconds"


async def test_cron_trigger_minutes(hassette_logging: Hassette):  # noqa
    start_time = SystemDateTime(2025, 8, 18, 0, 0, 0)

    trig = CronTrigger.from_arguments(second="0", minute="*/1", start=start_time)
    assert trig.cron_expression == "*/1 0 * * * 0"

    trig_next_time = trig.cron_iter.get_next()

    delta = SystemDateTime.from_py_datetime(trig_next_time) - start_time

    assert delta.in_seconds() == 60, f"Delta was {delta.in_seconds()} seconds"
