"""Interruptible thread-pool executor primitive.

Ported from Home Assistant's ``homeassistant.util.thread`` and
``homeassistant.util.executor``, with one adaptation: the shutdown join/interrupt
budget is a ``timeout: float`` parameter rather than a hard-coded module constant.

This module has **no Hassette imports** — it is a standalone primitive that can be
unit-tested in complete isolation from the rest of the framework.
"""

import contextlib
import ctypes
import inspect
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from logging import getLogger
from threading import Thread
from typing import Any

LOGGER = getLogger(__name__)

# Number of join/interrupt loop iterations before giving up on remaining threads.
_JOIN_ATTEMPTS = 10

# Maximum number of attempts on which straggler stacks are logged (to avoid log spam).
_MAX_LOG_ATTEMPTS = 2


def async_raise(tid: int, exctype: type[BaseException]) -> None:
    """Raise an exception asynchronously in the thread with id *tid*.

    Ported verbatim from ``homeassistant.util.thread.async_raise`` (HA
    ``homeassistant/util/thread.py:38-55``).

    Args:
        tid: The native integer thread id (``thread.ident``).
        exctype: The exception *class* to raise (not an instance).

    Raises:
        TypeError: If *exctype* is not a class.
        ValueError: If no thread with id *tid* exists.
        SystemError: If ``PyThreadState_SetAsyncExc`` returned ``> 1`` (interpreter
            state has been partially corrupted; it is reverted before raising).
    """
    if not inspect.isclass(exctype):
        raise TypeError("Only types can be raised (not instances)")

    c_tid = ctypes.c_ulong(tid)  # changed in python 3.7+
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(c_tid, ctypes.py_object(exctype))

    if res == 1:
        return

    if res == 0:
        raise ValueError("Thread not found")

    # "if it returns a number greater than one, you're in trouble,
    # and you should call it again with exc=NULL to revert the effect"
    ctypes.pythonapi.PyThreadState_SetAsyncExc(c_tid, None)
    raise SystemError("PyThreadState_SetAsyncExc failed")


def _log_thread_running_at_shutdown(name: str, ident: int) -> None:
    """Log the name and current stack of a thread still alive at shutdown.

    Equivalent to HA's ``_log_thread_running_at_shutdown``
    (``homeassistant/util/executor.py:23-32``).
    """
    frames = sys._current_frames()
    stack = frames.get(ident)
    formatted_stack = traceback.format_stack(stack)
    LOGGER.warning(
        "Thread[%s] is still running at shutdown: %s",
        name,
        "".join(formatted_stack).strip(),
    )


def join_or_interrupt_threads(threads: set[Thread], timeout: float, log: bool) -> set[Thread]:
    """Attempt to join or interrupt a set of threads within *timeout* seconds.

    Each thread receives an equal share of *timeout*. Threads that survive their
    slice are logged (when *log* is ``True``) and receive ``async_raise(SystemExit)``.
    Benign ``SystemError``/``ValueError`` races are suppressed — a ``ValueError``
    ("Thread not found") here means the thread died between the liveness check and
    the ``async_raise`` call, which is the intended outcome.

    Args:
        threads: The live threads to join or interrupt.
        timeout: Total seconds budgeted for this round.
        log: Whether to log stragglers' names and stacks before interrupting.

    Returns:
        The subset of *threads* that successfully joined (are no longer alive).
    """
    joined: set[Thread] = set()
    if not threads:
        return joined
    timeout_per_thread = timeout / len(threads)

    for thread in threads:
        thread.join(timeout=timeout_per_thread)

        if not thread.is_alive() or thread.ident is None:
            joined.add(thread)
            continue

        if log:
            _log_thread_running_at_shutdown(thread.name, thread.ident)

        with contextlib.suppress(SystemError, ValueError):
            # SystemError or ValueError at this stage is usually a benign
            # race condition where the thread dies right before we force
            # it to raise the exception.
            async_raise(thread.ident, SystemExit)

    return joined


class InterruptibleThreadPoolExecutor(ThreadPoolExecutor):
    """A ``ThreadPoolExecutor`` that will not deadlock on shutdown.

    Ported from ``homeassistant.util.executor.InterruptibleThreadPoolExecutor``
    (HA ``homeassistant/util/executor.py:61-101``). The only deviation from a verbatim
    port is that the join/interrupt budget is a ``timeout: float`` parameter on
    ``shutdown()`` and ``join_threads_or_timeout()``, instead of the HA module constant
    ``EXECUTOR_SHUTDOWN_TIMEOUT``.

    At shutdown, worker threads still alive after a join budget receive
    ``async_raise(thread.ident, SystemExit)`` on a best-effort basis. Threads blocked
    in a C call (``time.sleep``, ``socket.recv``) cannot be interrupted until they
    return to the Python interpreter; they are logged and abandoned when the budget
    expires. This is the accepted behaviour, matching HA.
    """

    def shutdown(
        self,
        *args: Any,
        join_threads_or_timeout: bool = True,
        timeout: float = 10.0,
        **kwargs: Any,
    ) -> None:
        """Shut down the executor with optional join/interrupt support.

        Calls ``super().shutdown(wait=False, cancel_futures=True)`` so that queued
        futures are cancelled immediately, then runs the join-or-interrupt loop if
        *join_threads_or_timeout* is ``True``.

        Args:
            *args: Forwarded to the base ``ThreadPoolExecutor.shutdown``.
            join_threads_or_timeout: When ``True`` (default), attempt to join live
                worker threads and interrupt stragglers within *timeout* seconds.
            timeout: Total seconds budgeted for the join/interrupt loop. Defaults to
                ``10.0`` (HA's ``EXECUTOR_SHUTDOWN_TIMEOUT``). The caller should pass
                the remaining shutdown budget rather than the raw configured value so
                the loop never overruns the total shutdown timeout.
            **kwargs: Forwarded to the base ``ThreadPoolExecutor.shutdown``.
        """
        super().shutdown(wait=False, cancel_futures=True)
        if join_threads_or_timeout:
            self.join_threads_or_timeout(timeout)

    def join_threads_or_timeout(self, timeout: float) -> None:
        """Join worker threads or give up after *timeout* seconds.

        Runs up to ``_JOIN_ATTEMPTS`` rounds of ``join_or_interrupt_threads``, each
        given a slice of the remaining budget. Exits early if all threads have joined.
        C-blocked threads that survive the full budget are abandoned — shutdown still
        completes, matching HA's best-effort guarantee.

        Args:
            timeout: Maximum total seconds to spend joining/interrupting threads.
        """
        remaining_threads = set(self._threads)  # pyright: ignore[reportAttributeAccessIssue]
        start_time = time.monotonic()
        timeout_remaining: float = timeout
        attempt = 0

        while True:
            if not remaining_threads:
                return

            attempt += 1

            # Each round gets remaining_budget / _JOIN_ATTEMPTS, so later rounds get
            # geometrically smaller slices. This is accepted HA behaviour — early rounds
            # are the most effective; later rounds are a best-effort tail.
            remaining_threads -= join_or_interrupt_threads(
                remaining_threads,
                timeout_remaining / _JOIN_ATTEMPTS,
                attempt <= _MAX_LOG_ATTEMPTS,
            )

            timeout_remaining = timeout - (time.monotonic() - start_time)
            if timeout_remaining <= 0:
                return
