import asyncio
import concurrent.futures
import contextlib

import pytest

from hassette.task_bucket import TaskBucket


async def sleeper():
    try:
        await asyncio.sleep(10)  # long sleep; will be cancelled
    except asyncio.CancelledError:
        # simulate well-behaved cleanup
        await asyncio.sleep(0)
        raise


async def test_cancel_all_cancels_cooperative_tasks(bucket_fixture: TaskBucket):
    """cancel_all cooperatively stops tracked tasks."""
    cooperative_task = asyncio.create_task(sleeper(), name="cooperative")
    # factory should auto-register; no explicit bucket.add/spawn needed
    await asyncio.sleep(0)  # let it start

    assert len(bucket_fixture) >= 1, f"bucket should track at least one task, tracks {len(bucket_fixture)}"

    await bucket_fixture.cancel_all()

    loop = asyncio.get_running_loop()
    current_time = loop.time()
    cancellation_deadline = current_time + bucket_fixture.config_cancel_timeout + 0.5
    while not cooperative_task.done() and current_time < cancellation_deadline:
        await asyncio.sleep(0.01)
        current_time = loop.time()

    assert cooperative_task.done(), f"task should be done after cancel_all, is {cooperative_task._state}"
    assert cooperative_task.cancelled(), "task should be cancelled after cancel_all"


async def boom(event: asyncio.Event):
    await asyncio.sleep(0)
    event.set()
    raise RuntimeError("boom")


async def test_crash_invokes_exception_recorder(bucket_fixture: TaskBucket):
    """Task crashes are observed via the exception recorder callback."""
    task_started = asyncio.Event()
    recorded: list[tuple[asyncio.Task, BaseException]] = []

    def recorder(t: asyncio.Task, exc: BaseException) -> None:
        recorded.append((t, exc))

    bucket_fixture.install_exception_recorder(recorder)

    try:
        crashing_task = asyncio.create_task(boom(task_started), name="exploder")
        await task_started.wait()
        await asyncio.sleep(0)  # let done callbacks fire

        assert crashing_task.done()
        assert not crashing_task.cancelled()
        assert len(recorded) == 1
        assert recorded[0][0] is crashing_task
        assert isinstance(recorded[0][1], RuntimeError)
    finally:
        bucket_fixture.uninstall_exception_recorder(recorder)


async def stubborn(event: asyncio.Event):
    loop = asyncio.get_running_loop()
    end = loop.time() + 1  # longer than bucket timeout
    while loop.time() < end:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(0.01)
    event.set()


async def test_stubborn_task_survives_cancel_all(bucket_fixture: TaskBucket):
    """Tasks that ignore cancellation finish on their own terms after cancel_all."""
    stubborn_task_finished = asyncio.Event()
    stubborn_task_handle = asyncio.create_task(stubborn(stubborn_task_finished), name="stubborn")

    assert len(bucket_fixture) >= 1, f"bucket should track at least one task, tracks {len(bucket_fixture)}"

    await asyncio.sleep(0)

    await bucket_fixture.cancel_all()
    await stubborn_task_finished.wait()
    await asyncio.sleep(0)

    assert stubborn_task_handle.done()
    assert not stubborn_task_handle.cancelled()


async def test_factory_tracks_rogue_create_task(bucket_fixture: TaskBucket):
    """Task factory picks up plain asyncio.create_task usage."""
    rogue_task_started = asyncio.Event()

    async def rogue():
        bucket_fixture.post_to_loop(rogue_task_started.set)
        await asyncio.sleep(10)

    rogue_task_handle = asyncio.create_task(rogue(), name="rogue")
    await asyncio.sleep(0)
    await rogue_task_started.wait()
    # No direct bucket.add; rely on factory
    assert len(bucket_fixture) >= 1, f"bucket should track at least one task, tracks {len(bucket_fixture)}"

    await bucket_fixture.cancel_all()
    assert rogue_task_handle.done(), f"task should be done after cancel_all, is {rogue_task_handle._state}"
    assert rogue_task_handle.cancelled(), "task should be cancelled after cancel_all"


async def test_run_sync_raises_inside_loop(bucket_fixture: TaskBucket) -> None:
    """run_sync rejects being invoked inside the running event loop."""

    async def sample_coroutine():
        return 42

    with pytest.raises(RuntimeError):
        bucket_fixture.run_sync(sample_coroutine())


async def test_run_sync_drives_coroutine_from_worker_thread(bucket_fixture: TaskBucket) -> None:
    """run_sync bridges a coroutine from a worker thread onto the running loop and returns its result.

    This is the path every sync facade (api/bus/scheduler/entity) depends on: a sync caller
    off the loop thread drives an async method to completion via run_coroutine_threadsafe.
    Calling through asyncio.to_thread is what makes the run_sync loop-guard pass instead of raise.
    """

    async def add(a: int, b: int) -> int:
        await asyncio.sleep(0)
        return a + b

    result = await asyncio.to_thread(bucket_fixture.run_sync, add(2, 3))
    assert result == 5


async def test_run_sync_timeout_zero_fails_immediately(bucket_fixture: TaskBucket) -> None:
    """timeout_seconds=0 fails immediately instead of falling back to the config default.

    Guards the ``if timeout_seconds is None`` semantics: an explicit 0 is a real value, not
    ``None``, so it must not be replaced by the (non-zero) configured default.
    """

    async def never_returns() -> None:
        await asyncio.sleep(100)

    with pytest.raises(concurrent.futures.TimeoutError):
        await asyncio.to_thread(bucket_fixture.run_sync, never_returns(), timeout_seconds=0)
