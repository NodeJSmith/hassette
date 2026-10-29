"""Hassette framework server entry point."""

import asyncio
import logging
import os
import signal
import threading
import time
from contextlib import suppress
from logging import getLogger

from hassette import Hassette, HassetteConfig
from hassette.exceptions import AppPrecheckFailedError, ConfigError
from hassette.resources.lifecycle import request_shutdown
from hassette.task_bucket.interruptible_executor import log_thread_running_at_shutdown

LOGGER = getLogger(__name__)

EX_CONFIG = 78
"""sysexits.h ``EX_CONFIG``: the configuration must be edited before a restart can succeed.

Raised for a `ConfigError` and for a failed app precheck (an app file must be edited). Supervisors
key on it (systemd ``RestartPreventExitStatus=78``, the add-on's s6 ``finish`` script).
"""

EX_SOFTWARE = 70
"""sysexits.h ``EX_SOFTWARE``: ``hassette run`` hard-exited after a clean stop, abandoning work still running.

Either hard exit uses it in place of 0, so a supervisor can tell a stop that cut work off from a clean one, as
systemd does for a stop that runs past ``TimeoutStopSec``. An exit already mapped to 1 or ``EX_CONFIG`` keeps
that code, since it says more.
"""

EXIT_BUDGET_SECONDS = 5.0
"""How long ``hassette run``'s exit check waits, after the shutdown snapshot, for cancelled tasks to finish.

5s matches Home Assistant core's fixed timeout for tasks at exit. It is one deadline for the whole exit, so
it fits inside the supervisor's stop grace (spec 141 D4).
"""

EXIT_WATCHDOG_MARGIN_SECONDS = 1.0
"""How long after the exit budget the exit watchdog fires, so a surviving task is named by the task check first."""


def exit_code_for(exc: BaseException | None) -> int:
    """The exit code ``hassette run`` maps a server run's outcome to.

    A clean stop or a keyboard interrupt is 0, a config error or failed app precheck ``EX_CONFIG``, and a
    fatal error or anything else unexpected 1. A hard exit replaces the 0 with ``EX_SOFTWARE`` (``exit_after_run``).
    """
    if exc is None or isinstance(exc, KeyboardInterrupt):
        return 0
    if isinstance(exc, ConfigError | AppPrecheckFailedError):
        return EX_CONFIG
    return 1


async def exit_after_run(core: Hassette, exc: BaseException | None) -> None:
    """``hassette run``'s exit check, run once the server's run has ended, with ``exc`` its error if any.

    Waits for an in-flight shutdown snapshot first, so it isn't cut short. Then sets one deadline,
    ``EXIT_BUDGET_SECONDS`` away, and:

    - starts the exit watchdog (``start_exit_watchdog()``), which bounds everything after this function:
      ``asyncio.run()``'s executor shutdown, the interpreter's thread join and the atexit handlers;
    - cancels every other task on the loop and waits for them until the deadline. A task still alive then
      is a survivor: it is named in one ERROR, as is ``exc``, and the process hard-exits, because
      ``asyncio.run()``'s own cancel-and-gather would otherwise wait on it forever.

    Either hard exit uses the code ``hassette run`` maps ``exc`` to, or ``EX_SOFTWARE`` where that code is 0,
    so an exit that abandoned work never reads as a clean stop. Only ``hassette run`` calls this, never
    ``serve()``: unit tests run the server in-process on a shared loop, where cancelling every task or arming
    the watchdog would hit the whole test worker.
    """
    snapshot = core.shutdown_snapshot_task
    if snapshot is not None and not snapshot.done():
        # the snapshot's own done-callback logs its outcome
        with suppress(BaseException):
            await asyncio.shield(snapshot)

    deadline = time.monotonic() + EXIT_BUDGET_SECONDS
    # only the hard exits use this code, and one that abandoned work never reports a clean stop's 0
    hard_exit_code = EX_SOFTWARE if (mapped := exit_code_for(exc)) == 0 else mapped
    start_exit_watchdog(deadline + EXIT_WATCHDOG_MARGIN_SECONDS, hard_exit_code)

    survivors = await cancel_remaining_tasks(deadline)
    if not survivors:
        return
    if exc is not None and not isinstance(exc, KeyboardInterrupt):
        # the hard exit never returns to `hassette run`, whose handlers would otherwise report the failure
        LOGGER.error("Hassette is exiting after an error: %s", exc, exc_info=exc)
    LOGGER.error(
        "Exiting without waiting for tasks still running %.0fs after shutdown: %s",
        EXIT_BUDGET_SECONDS,
        ", ".join(survivors),
    )
    hard_exit(hard_exit_code)


async def cancel_remaining_tasks(deadline: float) -> list[str]:
    """Cancel every task on the loop but the current one, and return the names of those alive at ``deadline``.

    A task that finishes its cancellation in time is not a survivor. One whose cancellation ended in an
    exception other than ``CancelledError`` (a cleanup that raised) is logged at WARNING; a clean cancel logs
    nothing.
    """
    current = asyncio.current_task()
    tasks = [task for task in asyncio.all_tasks() if task is not current]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=max(0.0, deadline - time.monotonic()))
    # Retrieving each finished task's exception keeps asyncio from logging "exception was never retrieved"
    # for it at exit, so for an untracked task this WARNING is the only report. A bucket-tracked task's
    # crash was already logged at ERROR by its bucket, so WARNING keeps the second line from reading as a
    # second failure.
    for task in tasks:
        if task.done() and not task.cancelled() and (task_exc := task.exception()) is not None:
            LOGGER.warning("Task %s raised during the exit cancellation", task.get_name(), exc_info=task_exc)
    return [task.get_name() for task in tasks if not task.done()]


def start_exit_watchdog(fire_at: float, code: int) -> None:
    """Start a daemon thread that hard-exits with ``code`` if the process is still alive at ``fire_at``.

    ``fire_at`` is on ``time.monotonic()``'s clock. When it fires, it logs one ERROR naming every live
    thread, then each one's stack (the main thread's shows where a frozen loop or a hung atexit handler is
    blocked). Threads are never judged one by one: a clean exit ends before it fires, however many threads
    it had. The user's atexit handlers don't run after it fires, as under a supervisor's kill.
    """

    def watch() -> None:
        time.sleep(max(0.0, fire_at - time.monotonic()))
        current = threading.current_thread()
        alive = [thread for thread in threading.enumerate() if thread is not current]
        LOGGER.error(
            "Hassette did not finish exiting in time; exiting with these threads alive: %s",
            ", ".join(thread.name for thread in alive),
        )
        for thread in alive:
            if thread.ident is not None:
                log_thread_running_at_shutdown(thread.name, thread.ident)
        hard_exit(code)

    threading.Thread(target=watch, name="hassette-exit-watchdog", daemon=True).start()


def hard_exit(code: int) -> None:
    """Flush logging, then end the process at once with ``code``, skipping interpreter finalization."""
    logging.shutdown()
    os._exit(code)


def _handle_sigint_signal(core: Hassette, loop: asyncio.AbstractEventLoop, sigint_seen: threading.Event) -> None:
    """Handle one SIGINT delivery: force-exit if a SIGINT was already seen, else request it.

    "Already seen" is tracked via ``sigint_seen`` — a plain ``threading.Event`` set immediately
    here on the first delivery — rather than ``core.shutdown_event``. The latter only becomes
    set once ``request_shutdown()`` actually runs on the loop thread via
    ``call_soon_threadsafe``, which may not have happened yet if the loop is blocked by
    *anything*, not only a stalled shutdown hook. Waiting on ``shutdown_event`` would make every
    SIGINT delivered before the loop catches up look like "the first one," defeating the
    second-Ctrl+C escalation exactly when it's most needed. The graceful path is still handed to
    the loop via ``call_soon_threadsafe``, matching how ``request_shutdown`` is invoked
    everywhere else; the force-exit path runs directly here, with no dependency on the loop or
    main thread ever regaining control.
    """
    if sigint_seen.is_set():
        LOGGER.warning("second SIGINT received during shutdown; forcing immediate exit")
        os._exit(1)

    sigint_seen.set()
    loop.call_soon_threadsafe(request_shutdown, core, "SIGINT received")


def _sigint_wait_loop(core: Hassette, loop: asyncio.AbstractEventLoop, sigint_seen: threading.Event) -> None:
    """Dedicated thread that synchronously waits for SIGINT via ``signal.sigwait()``.

    ``serve()`` blocks SIGINT process-wide before this thread (or any other) is created, so
    every thread the framework later spawns (the sync executor pool, the logging
    ``QueueListener``, etc.) inherits the blocked mask and is never an eligible target for the
    kernel to deliver SIGINT to. POSIX guarantees a thread blocked in ``sigwait()`` for a signal
    takes delivery priority for it, so this thread — and only this thread — ever receives it,
    regardless of what the main/event-loop thread happens to be doing at the time.

    This matters because a plain ``signal.signal()`` handler still depends on which thread the
    OS chooses to deliver a process-directed signal to in a multi-threaded process — hassette
    runs several. If the kernel picks a thread other than the one blocked inside a stalled
    shutdown hook, that hook's blocking call is never interrupted and the force-exit escalation
    silently misses its window. See ``tests/system/test_sigint_shutdown.py`` for the
    reproduction.
    """
    while True:
        signal.sigwait({signal.SIGINT})
        _handle_sigint_signal(core, loop, sigint_seen)


def create_core(config: HassetteConfig) -> Hassette:
    """Check the config and build the wired ``Hassette`` core a server run drives."""
    config.require_token()
    config.ensure_directories()
    core = Hassette(config=config)
    core.wire_services()
    return core


async def serve(core: Hassette) -> None:
    """Install the signal handling and run ``core`` until it stops."""
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, request_shutdown, core, "SIGTERM received")
    except NotImplementedError:
        LOGGER.warning("SIGTERM handler registration is not supported on this platform/event loop")

    # Block SIGINT before any other thread exists, so every thread created later (the sync
    # executor pool, the logging QueueListener, etc. — all spawned during run_forever()'s
    # resource initialization, after this point) inherits the blocked mask — see
    # _sigint_wait_loop's docstring. sigwait()/pthread_sigmask() are POSIX-only; hassette does
    # not target Windows (see pyproject.toml — no Windows classifier), so no fallback is
    # provided there.
    sigint_seen = threading.Event()
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    except AttributeError:
        LOGGER.warning("SIGINT handling via sigwait() is not supported on this platform")
    else:
        threading.Thread(target=_sigint_wait_loop, args=(core, loop, sigint_seen), daemon=True).start()

    await core.run_forever()


async def run(config: HassetteConfig) -> None:
    """``hassette run``'s coroutine: serve the configured core, then run the exit check on either path."""
    core = create_core(config)
    try:
        await serve(core)
    except BaseException as exc:
        await exit_after_run(core, exc)
        raise
    await exit_after_run(core, None)
