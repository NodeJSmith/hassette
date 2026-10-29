"""One real process exit through ``hassette.server.exit_after_run()``: ``exit_child.py <scenario> <budget>``.

Run by ``test_exit_after_run.py`` as a subprocess, so the hard exit and the watchdog end a real process.
It runs ``hassette run``'s coroutine, ``server.run()``, inside ``asyncio.run()``, with the core's construction and
serving swapped for a scenario that leaves work behind and then ends (or raises). Logs go to stderr.
"""

import asyncio
import atexit
import concurrent.futures
import contextlib
import logging
import sys
import threading
import time
from types import SimpleNamespace

import anyio.to_thread

from hassette import server
from hassette.exceptions import FatalError

SCENARIO = sys.argv[1]
server.EXIT_BUDGET_SECONDS = float(sys.argv[2])
server.EXIT_WATCHDOG_MARGIN_SECONDS = 0.3


async def swallow_cancellation() -> None:
    while True:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(1000)


async def block_in_cancellation_cleanup() -> None:
    try:
        await asyncio.sleep(1000)
    except asyncio.CancelledError:  # noqa: ASYNC103 — never returns, by design
        time.sleep(1000)  # noqa: ASYNC251 — a blocking sync call in cancellation cleanup freezes the loop


async def finish_cancellation_slowly() -> None:
    try:
        await asyncio.sleep(1000)
    except asyncio.CancelledError:
        await asyncio.sleep(1.0)
        raise


def hang_at_exit() -> None:
    time.sleep(1000)


async def write_snapshot() -> bool:
    await asyncio.sleep(0.3)
    print("snapshot written", file=sys.stderr, flush=True)
    return True


async def play_run(core: SimpleNamespace, keep: list[object]) -> None:
    """Set up what the scenario leaves behind when the server's run ends, then end it (or raise).

    Tasks and pools are kept in ``keep``, so nothing is collected before the exit check sees it.
    """
    loop = asyncio.get_running_loop()
    if SCENARIO.startswith("swallowing_task"):
        keep.append(loop.create_task(swallow_cancellation(), name="swallower"))
    if SCENARIO.startswith("stuck_thread"):
        threading.Thread(target=time.sleep, args=(1000,), name="user-device-client").start()
    if SCENARIO == "daemon_thread":
        threading.Thread(target=time.sleep, args=(1000,), name="user-daemon", daemon=True).start()
    if SCENARIO == "idle_anyio":
        await anyio.to_thread.run_sync(lambda: None)
    if SCENARIO == "idle_stdlib_pool":
        pool = concurrent.futures.ThreadPoolExecutor(2, thread_name_prefix="user-pool")
        keep.append(pool)
        pool.submit(lambda: None).result()
    if SCENARIO == "stuck_stdlib_pool":
        pool = concurrent.futures.ThreadPoolExecutor(2, thread_name_prefix="user-pool")
        keep.append(pool)
        pool.submit(time.sleep, 1000)
    if SCENARIO == "frozen_loop":
        keep.append(loop.create_task(block_in_cancellation_cleanup(), name="bad-cleanup"))
    if SCENARIO == "hung_atexit":
        atexit.register(hang_at_exit)
    if SCENARIO == "slow_cancellation":
        keep.append(loop.create_task(finish_cancellation_slowly(), name="slow-cleanup"))
    if SCENARIO == "snapshot":
        core.shutdown_snapshot_task = loop.create_task(write_snapshot(), name="snapshot")
    await asyncio.sleep(0.1)  # let each task reach its first await
    if SCENARIO.endswith("_fatal"):
        raise FatalError("fatal")


async def main() -> None:
    core = SimpleNamespace(shutdown_snapshot_task=None)
    keep: list[object] = []
    server.create_core = lambda _config: core  # pyright: ignore[reportAttributeAccessIssue]
    server.serve = lambda _core: play_run(core, keep)  # pyright: ignore[reportAttributeAccessIssue]
    await server.run(None)  # pyright: ignore[reportArgumentType]


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        asyncio.run(main())
    except FatalError:
        sys.exit(server.exit_code_for(FatalError("fatal")))
