import asyncio
import contextlib
import logging

from hassette.core.classes import tasks


async def sleeper():
    try:
        await asyncio.sleep(10)  # long sleep; will be cancelled
    except asyncio.CancelledError:
        # simulate well-behaved cleanup
        await asyncio.sleep(0)
        raise


async def test_cancel_all_cancels_cooperative_tasks(bucket_fixture: tasks.TaskBucket):
    t = asyncio.create_task(sleeper(), name="cooperative")
    # factory should auto-register; no explicit bucket.add/spawn needed
    await asyncio.sleep(0)  # let it start

    assert len(bucket_fixture) >= 1, f"bucket should track at least one task, tracks {len(bucket_fixture)}"

    await bucket_fixture.cancel_all()

    time = asyncio.get_running_loop().time()
    end = time + bucket_fixture.cancel_timeout + 0.5
    while not t.done() and time < end:
        await asyncio.sleep(0.01)
        time = asyncio.get_running_loop().time()

    assert t.done(), f"task should be done after cancel_all, is {t._state}"
    assert t.cancelled(), "task should be cancelled after cancel_all"


async def boom(event: asyncio.Event):
    await asyncio.sleep(0)
    event.set()
    raise RuntimeError("boom")


async def test_crash_is_logged(bucket_fixture: tasks.TaskBucket, caplog):
    event = asyncio.Event()
    caplog.set_level(logging.DEBUG, logger=bucket_fixture.logger.name)
    t = asyncio.create_task(boom(event), name="exploder")

    num_tasks = len(bucket_fixture)
    assert num_tasks >= 1, f"bucket should track at least one task, tracks {num_tasks}"

    await event.wait()
    await asyncio.sleep(0.2)  # let it crash and log

    msgs = [r.getMessage() for r in caplog.records]

    if not any("exploder" in m and "crashed" in m for m in msgs):
        raise AssertionError(f"No error log; logs were: {msgs}")

    assert t.done(), f"task should be done after crash, is {t._state}"
    assert not t.cancelled(), "task should not be cancelled after crash"


async def stubborn(event: asyncio.Event):
    loop = asyncio.get_running_loop()
    end = loop.time() + 1  # longer than bucket timeout
    while loop.time() < end:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(0.01)
    event.set()


async def test_warns_on_stubborn_tasks(bucket_fixture: tasks.TaskBucket, caplog):
    event = asyncio.Event()
    caplog.set_level(logging.WARNING, logger=bucket_fixture.logger.name)
    t = asyncio.create_task(stubborn(event), name="stubborn")

    assert len(bucket_fixture) >= 1, f"bucket should track at least one task, tracks {len(bucket_fixture)}"

    await asyncio.sleep(0)

    await bucket_fixture.cancel_all()
    await event.wait()
    await asyncio.sleep(0)

    # the task may still be running (ignored cancel), but we should have warned
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    if not any("refused" in m for m in warnings):
        raise AssertionError(f"No stubborn warning; logs were: {warnings}")

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(event.wait(), timeout=bucket_fixture.cancel_timeout + 0.5)

    assert t.done(), f"task should be done after finishing, is {t._state}"
    assert not t.cancelled(), "task should not be cancelled after finishing"


async def test_factory_tracks_rogue_create_task(bucket_fixture: tasks.TaskBucket):
    ran = asyncio.Event()

    async def rogue():
        ran.set()
        await asyncio.sleep(10)

    t = asyncio.create_task(rogue(), name="rogue")
    await asyncio.sleep(0)
    await ran.wait()
    # No direct bucket.add; rely on factory
    assert len(bucket_fixture) >= 1, f"bucket should track at least one task, tracks {len(bucket_fixture)}"

    await bucket_fixture.cancel_all()
    assert t.done(), f"task should be done after cancel_all, is {t._state}"
    assert t.cancelled(), "task should be cancelled after cancel_all"
