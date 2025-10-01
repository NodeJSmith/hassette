import asyncio
from zoneinfo import ZoneInfo

from whenever import SystemDateTime

from hassette.core.scheduler import Scheduler
from hassette.core.scheduler.classes import ScheduledJob
from hassette.core.scheduler.triggers import now

TZ = ZoneInfo("America/Chicago")


async def test_run_in_passes_args_kwargs_async(hassette_scheduler: Scheduler) -> None:
    called = asyncio.Event()
    received: list[tuple[int, int, bool]] = []

    async def target(a: int, b: int, *, flag: bool) -> None:
        received.append((a, b, flag))
        called.set()

    job = hassette_scheduler.run_in(target, delay=0.01, args=(1, 2), kwargs={"flag": True})

    await asyncio.wait_for(called.wait(), timeout=1)
    job.cancel()

    assert received == [(1, 2, True)]


async def test_run_in_passes_args_kwargs_sync(hassette_scheduler: Scheduler) -> None:
    loop = asyncio.get_running_loop()
    called = asyncio.Event()
    received: list[tuple[str, int]] = []

    def target(name: str, *, count: int) -> None:
        received.append((name, count))
        loop.call_soon_threadsafe(called.set)

    job = hassette_scheduler.run_in(target, delay=0.01, args=("sensor",), kwargs={"count": 3})

    await asyncio.wait_for(called.wait(), timeout=1)
    job.cancel()

    assert received == [("sensor", 3)]


def test_scheduled_job_copies_args_kwargs() -> None:
    args = [1, 2]
    kwargs = {"alpha": 99}

    job = ScheduledJob(
        owner="owner",
        next_run=SystemDateTime(2030, 1, 1, 0, 0, 0),
        job=lambda *a, **kw: None,  # noqa
        args=args,  # type: ignore
        kwargs=kwargs,
    )

    args.append(3)
    kwargs["alpha"] = 0

    assert job.args == (1, 2)
    assert job.kwargs == {"alpha": 99}


async def test_jobs_execute_in_run_order(hassette_scheduler: Scheduler) -> None:
    order: list[str] = []
    early_done = asyncio.Event()
    late_done = asyncio.Event()

    def make_job(label: str, signal: asyncio.Event):
        def _job() -> None:
            order.append(label)
            signal.set()

        return _job

    reference = now()
    hassette_scheduler.run_once(make_job("late", late_done), run_at=reference.add(seconds=0.4))
    hassette_scheduler.run_once(make_job("early", early_done), run_at=reference.add(seconds=0.1))

    await asyncio.wait_for(early_done.wait(), timeout=2)
    await asyncio.wait_for(late_done.wait(), timeout=2)

    assert order[:2] == ["early", "late"]
