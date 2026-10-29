# pyright: basic, reportOptionalOperand=false, reportAttributeAccessIssue=false, reportConstantRedefinition=false, reportOperatorIssue=false
# ruff: noqa
# Throwaway probe kept verbatim as the evidence spec 141 D3 cites; not maintained code.
"""One exit-path run: child.py <design> <scenario> <marker_dir>.

design: base (today, unbounded), L (ledger D3: task poll + os._exit, bounded executor shutdown, patched
threading._shutdown with atexit helper), W (one daemon watchdog armed after run_forever ends).
"""

import asyncio
import atexit
import concurrent.futures
import os
import sys
import threading
import time

BUDGET = 2.0
DESIGN, SCENARIO, MARK = sys.argv[1], sys.argv[2], sys.argv[3]
DEADLINE = None  # L's module-level deadline, as D4 describes


def log(msg):
    sys.stderr.write(f"[{DESIGN}] {msg}\n")
    sys.stderr.flush()


def mark(name):
    open(os.path.join(MARK, name), "w").close()


def user_atexit():
    mark("user_atexit_ran")


atexit.register(user_atexit)


async def run_forever():
    """Stand-in for core.run_forever(): set up the scenario, then return (or raise)."""
    loop = asyncio.get_running_loop()
    s = SCENARIO
    if s in ("stuck_user_thread", "error_stuck_thread"):
        threading.Thread(target=time.sleep, args=(1000,), name="user-device-client").start()
    if s == "idle_stdlib_pool":
        pool = concurrent.futures.ThreadPoolExecutor(2, thread_name_prefix="user-pool")
        pool.submit(lambda: None).result()
    if s == "idle_anyio":
        import anyio.to_thread

        await anyio.to_thread.run_sync(lambda: None)
    if s == "hung_atexit":
        atexit.register(time.sleep, 1000)
    if s == "stuck_default_executor":
        loop.run_in_executor(None, time.sleep, 1000)
        await asyncio.sleep(0.1)
    if s == "frozen_loop":

        async def bad_cleanup():
            try:
                await asyncio.sleep(1000)
            except asyncio.CancelledError:  # noqa: ASYNC103
                time.sleep(1000)  # blocking sync call in cancellation cleanup

        loop.create_task(bad_cleanup(), name="bad-cleanup")
        await asyncio.sleep(0.1)
    if s == "swallowing_task":

        async def swallow():
            while True:
                try:
                    await asyncio.sleep(1000)
                except asyncio.CancelledError:  # noqa: ASYNC103
                    pass

        loop.create_task(swallow(), name="swallower")
        await asyncio.sleep(0.1)
    if s == "error_stuck_thread":
        raise RuntimeError("fatal")


def code_for(exc):
    return 0 if exc is None else 1


# ---- W ----
def arm_watchdog(exc):
    deadline = time.monotonic() + BUDGET
    code = code_for(exc)

    def watch():
        time.sleep(max(0.0, deadline - time.monotonic()))
        alive = [t.name for t in threading.enumerate() if t is not threading.current_thread()]
        log(f"WATCHDOG fired; alive: {alive}")
        mark("survivor_logged")
        os._exit(code)

    threading.Thread(target=watch, name="exit-watchdog", daemon=True).start()


# ---- L ----
async def l_task_half(exc):
    me = asyncio.current_task()
    tasks = [t for t in asyncio.all_tasks() if t is not me]
    for t in tasks:
        t.cancel()
    while any(not t.done() for t in tasks) and time.monotonic() < DEADLINE:
        await asyncio.sleep(0.05)
    left = [t.get_name() for t in tasks if not t.done()]
    if left:
        log(f"task survivors {left}; os._exit")
        mark("survivor_logged")
        os._exit(code_for(exc))


class GuardedPool(concurrent.futures.ThreadPoolExecutor):
    """Stand-in for InterruptibleThreadPoolExecutor plus D3's idempotence guard (second shutdown waits on nothing)."""

    def shutdown(self, wait=True, *, cancel_futures=False):
        if self._shutdown:
            return
        super().shutdown(wait=False, cancel_futures=True)


def l_executor_half(pool):
    pool.shutdown(wait=False, cancel_futures=True)
    for t in list(pool._threads):
        t.join(timeout=max(0.0, DEADLINE - time.monotonic()))


def l_patch_shutdown():
    orig_atexits = threading._threading_atexits

    def bounded_shutdown():
        helper = threading.Thread(
            target=lambda: [cb() for cb in reversed(list(orig_atexits))], name="atexit-helper", daemon=True
        )
        helper.start()
        helper.join(timeout=max(0.0, DEADLINE - time.monotonic()))
        main = threading.main_thread()
        survivors = []
        for t in threading.enumerate():
            if t is main or t.daemon:
                continue
            t.join(timeout=max(0.0, DEADLINE - time.monotonic()))
            if t.is_alive():
                survivors.append(t.name)
        if survivors:
            log(f"thread survivors {survivors}; interpreter continues exit")
            mark("survivor_logged")

    threading._shutdown = bounded_shutdown


async def main():
    global DEADLINE
    loop = asyncio.get_running_loop()
    pool = None
    if DESIGN == "L":
        pool = GuardedPool(thread_name_prefix="asyncio")
        loop.set_default_executor(pool)
    exc = None
    try:
        await run_forever()
    except BaseException as e:  # noqa: ASYNC103
        exc = e
    if DESIGN == "W":
        arm_watchdog(exc)
    elif DESIGN == "L":
        DEADLINE = time.monotonic() + BUDGET
        await l_task_half(exc)
        l_executor_half(pool)
        l_patch_shutdown()
    if exc is not None:
        raise exc


if __name__ == "__main__":
    mark("started")
    asyncio.run(main())
