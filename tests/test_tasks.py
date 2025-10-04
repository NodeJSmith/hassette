import asyncio
import contextlib
import logging

from hassette.core import tasks as core_tasks  # gives you the actual logger name


async def sleeper():
    try:
        await asyncio.sleep(10)  # long sleep; will be cancelled
    except asyncio.CancelledError:
        # simulate well-behaved cleanup
        await asyncio.sleep(0)
        raise


async def test_cancel_all_cancels_cooperative_tasks(bucket_fixture):
    t = asyncio.create_task(sleeper(), name="cooperative")
    # factory should auto-register; no explicit bucket.add/spawn needed
    await asyncio.sleep(0)  # let it start
    await bucket_fixture.cancel_all()

    assert t.done()
    assert t.cancelled()


async def boom(event: asyncio.Event):
    await asyncio.sleep(0)
    event.set()
    raise RuntimeError("boom")


async def test_crash_is_logged(bucket_fixture, caplog):
    event = asyncio.Event()
    caplog.set_level(logging.DEBUG, logger=core_tasks.LOGGER.name)
    t = asyncio.create_task(boom(event), name="exploder")

    num_tasks = len(bucket_fixture)
    assert num_tasks >= 1, f"bucket should track at least one task, tracks {num_tasks}"

    await event.wait()
    await asyncio.sleep(0.2)  # let it crash and log

    msgs = [r.getMessage() for r in caplog.records]
    # assert any("exploder" in m and "failed" in m for m in msgs)
    if not any("exploder" in m and "failed" in m for m in msgs):
        raise AssertionError(f"No error log; logs were: {msgs}")
    assert t.done()
    assert not t.cancelled()


async def stubborn(event: asyncio.Event):
    loop = asyncio.get_running_loop()
    end = loop.time() + 0.5  # longer than bucket timeout
    while loop.time() < end:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(0.01)
    event.set()


async def test_warns_on_stubborn_tasks(bucket_fixture, caplog):
    event = asyncio.Event()
    caplog.set_level(logging.WARNING, logger=core_tasks.LOGGER.name)
    t = asyncio.create_task(stubborn(event), name="stubborn")
    await asyncio.sleep(0)

    await bucket_fixture.cancel_all()

    # the task may still be running (ignored cancel), but we should have warned
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    # assert any("refused to die" in m for m in warnings)
    if not any("refused" in m for m in warnings):
        raise AssertionError(f"No stubborn warning; logs were: {warnings}")

    await asyncio.wait_for(event.wait(), timeout=bucket_fixture.cancel_timeout + 0.5)

    assert t.done()
    assert not t.cancelled()


async def test_factory_tracks_rogue_create_task(bucket_fixture):
    ran = asyncio.Event()

    async def rogue():
        ran.set()
        await asyncio.sleep(10)

    t = asyncio.create_task(rogue(), name="rogue")
    await asyncio.sleep(0)
    await ran.wait()
    # No direct bucket.add; rely on factory
    assert len(bucket_fixture) >= 1

    await bucket_fixture.cancel_all()
    assert t.done()
    assert t.cancelled()
