import asyncio
import contextlib
import logging

import pytest

from hassette.core.resources import task_bucket


async def sleeper():
    try:
        await asyncio.sleep(10)  # long sleep; will be cancelled
    except asyncio.CancelledError:
        # simulate well-behaved cleanup
        await asyncio.sleep(0)
        raise


async def test_cancel_all_cancels_cooperative_tasks(bucket_fixture: task_bucket.TaskBucket):
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


async def test_crash_is_logged(bucket_fixture: task_bucket.TaskBucket, caplog):
    """Task crashes are logged by the bucket."""
    task_started = asyncio.Event()
    caplog.set_level(logging.DEBUG, logger=bucket_fixture.logger.name)
    crashing_task = asyncio.create_task(boom(task_started), name="exploder")

    num_tasks = len(bucket_fixture)
    assert num_tasks >= 1, f"bucket should track at least one task, tracks {num_tasks}"

    await task_started.wait()
    await asyncio.sleep(0.2)  # let it crash and log

    log_messages = [record.getMessage() for record in caplog.records]

    if not any("exploder" in message and "crashed" in message for message in log_messages):
        raise AssertionError(f"No error log; logs were: {log_messages}")

    assert crashing_task.done(), f"task should be done after crash, is {crashing_task._state}"
    assert not crashing_task.cancelled(), "task should not be cancelled after crash"


async def stubborn(event: asyncio.Event):
    loop = asyncio.get_running_loop()
    end = loop.time() + 1  # longer than bucket timeout
    while loop.time() < end:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(0.01)
    event.set()


async def test_warns_on_stubborn_tasks(bucket_fixture: task_bucket.TaskBucket, caplog):
    """Bucket logs a warning when tasks ignore cancellation."""
    stubborn_task_finished = asyncio.Event()
    caplog.set_level(logging.WARNING, logger=bucket_fixture.logger.name)
    stubborn_task_handle = asyncio.create_task(stubborn(stubborn_task_finished), name="stubborn")

    assert len(bucket_fixture) >= 1, f"bucket should track at least one task, tracks {len(bucket_fixture)}"

    await asyncio.sleep(0)

    await bucket_fixture.cancel_all()
    await stubborn_task_finished.wait()
    await asyncio.sleep(0)

    # the task may still be running (ignored cancel), but we should have warned
    warning_messages = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    if not any("refused" in message for message in warning_messages):
        raise AssertionError(f"No stubborn warning; logs were: {warning_messages}")

    assert stubborn_task_handle.done(), f"task should be done after finishing, is {stubborn_task_handle._state}"
    assert not stubborn_task_handle.cancelled(), "task should not be cancelled after finishing"


async def test_factory_tracks_rogue_create_task(bucket_fixture: task_bucket.TaskBucket):
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


async def test_run_sync_raises_inside_loop(bucket_fixture: task_bucket.TaskBucket) -> None:
    """run_sync rejects being invoked inside the running event loop."""

    async def sample_coroutine():
        return 42

    with pytest.raises(RuntimeError):
        bucket_fixture.run_sync(sample_coroutine())
