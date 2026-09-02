"""Hassette framework server entry point."""

import asyncio
import os
import signal
import threading
from logging import getLogger

from hassette import Hassette, HassetteConfig
from hassette.exceptions import FatalError
from hassette.resources.lifecycle import request_shutdown

LOGGER = getLogger(__name__)


def _handle_sigint_signal(core: Hassette, loop: asyncio.AbstractEventLoop) -> None:
    """Handle one SIGINT delivery: force-exit if shutdown is already underway, else request it.

    The graceful path is handed to the loop via ``call_soon_threadsafe`` (this runs on a
    dedicated non-loop thread — see ``_sigint_wait_loop``), matching how ``request_shutdown``
    is invoked everywhere else. The force-exit path runs directly here instead, with no
    dependency on the loop or main thread ever regaining control — see ``_sigint_wait_loop``'s
    docstring for why that independence is the entire point.
    """
    if core.shutdown_event.is_set():
        LOGGER.warning("second SIGINT received during shutdown; forcing immediate exit")
        os._exit(1)

    loop.call_soon_threadsafe(request_shutdown, core, "SIGINT received")


def _sigint_wait_loop(core: Hassette, loop: asyncio.AbstractEventLoop) -> None:
    """Dedicated thread that synchronously waits for SIGINT via ``signal.sigwait()``.

    ``main()`` blocks SIGINT process-wide before this thread (or any other) is created, so
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
        _handle_sigint_signal(core, loop)


async def main(config: HassetteConfig) -> None:
    """Start the Hassette framework server with the provided configuration."""
    if not config.token:
        raise FatalError(
            "HA token is required for server startup. Set HASSETTE__TOKEN or HA_TOKEN in your environment or .env file."
        )

    config.ensure_directories()
    core = Hassette(config=config)
    core.wire_services()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, request_shutdown, core, "SIGTERM received")
    except NotImplementedError:
        LOGGER.warning("SIGTERM handler registration is not supported on this platform/event loop")

    # Block SIGINT before any other thread exists, so every thread created later (the sync
    # executor pool, the logging QueueListener, etc. — all spawned during run_forever()'s
    # resource initialization, after this point) inherits the blocked mask — see
    # _sigint_wait_loop's docstring. sigwait()/pthread_sigmask() are POSIX-only; on platforms
    # without them (Windows), SIGINT falls back to Python's default handling, same as before
    # this framework registered anything for it.
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    except AttributeError:
        LOGGER.warning("SIGINT handling via sigwait() is not supported on this platform")
    else:
        threading.Thread(target=_sigint_wait_loop, args=(core, loop), daemon=True).start()

    await core.run_forever()
