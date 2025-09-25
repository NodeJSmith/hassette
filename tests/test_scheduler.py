import asyncio
import contextlib
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from whenever import SystemDateTime

from hassette.core.core import Hassette, HassetteConfig
from hassette.core.scheduler import Scheduler
from hassette.core.scheduler.scheduler import ScheduledJob, _Scheduler

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


async def test_run_in_passes_args_kwargs_async(mock_scheduler: Scheduler) -> None:
    called = asyncio.Event()
    received: list[tuple[int, int, bool]] = []

    async def target(a: int, b: int, *, flag: bool) -> None:
        received.append((a, b, flag))
        called.set()

    job = mock_scheduler.run_in(target, delay=0.01, args=(1, 2), kwargs={"flag": True})

    await asyncio.wait_for(called.wait(), timeout=1)
    job.cancel()

    assert received == [(1, 2, True)]


async def test_run_in_passes_args_kwargs_sync(mock_scheduler: Scheduler) -> None:
    loop = asyncio.get_running_loop()
    called = asyncio.Event()
    received: list[tuple[str, int]] = []

    def target(name: str, *, count: int) -> None:
        received.append((name, count))
        loop.call_soon_threadsafe(called.set)

    job = mock_scheduler.run_in(target, delay=0.01, args=("sensor",), kwargs={"count": 3})

    await asyncio.wait_for(called.wait(), timeout=1)
    job.cancel()

    assert received == [("sensor", 3)]


def test_scheduled_job_copies_args_kwargs() -> None:
    args = [1, 2]
    kwargs = {"alpha": 99}

    job = ScheduledJob(
        next_run=SystemDateTime(2030, 1, 1, 0, 0, 0),
        job=lambda *a, **kw: None,  # noqa
        args=args,  # type: ignore
        kwargs=kwargs,
    )

    args.append(3)
    kwargs["alpha"] = 0

    assert job.args == (1, 2)
    assert job.kwargs == {"alpha": 99}
