import asyncio
from zoneinfo import ZoneInfo

from whenever import ZonedDateTime

from hassette import Hassette
from hassette.core.resources.scheduler.scheduler import ScheduledJob
from hassette.utils.date_utils import now

TZ = ZoneInfo("America/Chicago")


async def test_run_in_passes_args_kwargs_async(hassette_with_scheduler: Hassette) -> None:
    """run_in forwards args/kwargs to async callables."""
    job_executed = asyncio.Event()
    captured_arguments: list[tuple[int, int, bool]] = []

    async def target(a: int, b: int, *, flag: bool) -> None:
        captured_arguments.append((a, b, flag))
        job_executed.set()

    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=0.01, args=(1, 2), kwargs={"flag": True})

    await asyncio.wait_for(job_executed.wait(), timeout=1)
    scheduled_job.cancel()

    assert captured_arguments == [(1, 2, True)], f"Expected [(1, 2, True)], got {captured_arguments}"


async def test_run_in_passes_args_kwargs_sync(hassette_with_scheduler: Hassette) -> None:
    """run_in forwards args/kwargs to sync callables."""
    event_loop = asyncio.get_running_loop()
    job_executed = asyncio.Event()
    captured_arguments: list[tuple[str, int]] = []

    def target(name: str, *, count: int) -> None:
        captured_arguments.append((name, count))
        event_loop.call_soon_threadsafe(job_executed.set)

    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=0.01, args=("sensor",), kwargs={"count": 3})

    await asyncio.wait_for(job_executed.wait(), timeout=1)
    scheduled_job.cancel()

    assert captured_arguments == [("sensor", 3)], f"Expected [('sensor', 3)], got {captured_arguments}"


def test_scheduled_job_copies_args_kwargs() -> None:
    """ScheduledJob stores copies so external mutations do not leak in."""
    args = [1, 2]
    kwargs = {"alpha": 99}

    job = ScheduledJob(
        owner="owner",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda *a, **kw: None,  # noqa
        args=args,  # type: ignore
        kwargs=kwargs,
    )

    args.append(3)
    kwargs["alpha"] = 0

    assert job.args == (1, 2), f"Expected (1, 2), got {job.args}"
    assert job.kwargs == {"alpha": 99}, f"Expected {{'alpha': 99}}, got {job.kwargs}"


async def test_jobs_execute_in_run_order(hassette_with_scheduler: Hassette) -> None:
    """run_once executes jobs according to their scheduled time."""
    execution_order: list[str] = []
    early_job_complete = asyncio.Event()
    late_job_complete = asyncio.Event()

    def make_job(label: str, signal: asyncio.Event):
        def _job() -> None:
            execution_order.append(label)
            signal.set()

        return _job

    reference = now()
    hassette_with_scheduler._scheduler.run_once(make_job("late", late_job_complete), start=reference.add(seconds=0.4))
    hassette_with_scheduler._scheduler.run_once(make_job("early", early_job_complete), start=reference.add(seconds=0.1))

    await asyncio.wait_for(early_job_complete.wait(), timeout=2)
    await asyncio.wait_for(late_job_complete.wait(), timeout=2)

    actual = set(execution_order[:2])
    expected = {"early", "late"}
    assert actual == expected, f"Expected {expected}, got {actual}"
