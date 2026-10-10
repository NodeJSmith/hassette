"""Common execution tracking utility.

Provides a lightweight async context manager for timing and error capture,
used by both the scheduler and bus execution paths.
"""

import asyncio
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from hassette_wire import ExecutionStatus

from hassette.exceptions import DependencyError

MAX_TRACEBACK_SIZE = 8192
TRACEBACK_TRUNCATION_SUFFIX = "\n... [truncated]"


@dataclass
class ExecutionResult:
    """Captures timing and error information from a tracked execution."""

    execution_id: str | None = None
    monotonic_start: float = 0.0
    duration_ms: float = 0.0
    status: ExecutionStatus | None = None
    """Outcome of the tracked execution. ``None`` until ``track_execution()`` (or an equivalent
    caller) assigns a real value on exit — no code path reads ``status`` before that assignment,
    so there is no live "pending" state to represent."""
    error_message: str | None = None
    error_type: str | None = None
    error_traceback: str | None = None
    is_di_failure: bool = False
    """True when the execution failed due to a DependencyError (or subclass)."""

    exc: BaseException | None = None
    """The exception raised during execution, or None if the execution succeeded or was cancelled.
    Populated for both ``Exception`` and ``TimeoutError`` — not for ``CancelledError``."""

    thread_leaked: bool = False
    """True when the execution timed out and the sync worker thread was still alive after the timeout.

    Set by ``CommandExecutor._execute`` at the timeout site after reading the
    ``SyncWorkerHandle`` exposed by ``SyncExecutorService.submit()``.  False for async handlers,
    not-started timeouts (``handle.thread`` is ``None``), and all non-timed-out executions.

    Subject to a small race window: if the worker finishes between the timeout cancellation and the
    liveness check, this flag reads False even though the thread outlived the asyncio deadline.
    This is a false-negative (undercounting), not a false-positive. Treat as a lower bound.
    """

    @property
    def is_success(self) -> bool:
        return self.status == ExecutionStatus.SUCCESS

    @property
    def is_error(self) -> bool:
        return self.status == ExecutionStatus.ERROR

    @property
    def is_cancelled(self) -> bool:
        return self.status == ExecutionStatus.CANCELLED

    @property
    def is_timed_out(self) -> bool:
        return self.status == ExecutionStatus.TIMED_OUT


@asynccontextmanager
async def track_execution(
    known_errors: tuple[type[Exception], ...] = (),
    timeout: float | None = None,
) -> AsyncIterator[ExecutionResult]:
    """Async context manager that tracks execution timing and errors.

    Yields an ExecutionResult that is populated on exit. Always re-raises exceptions.

    Args:
        known_errors: A tuple of exception types (and their subclasses) for which
            ``error_traceback`` is suppressed (set to ``None``) in the result.
            Uses ``isinstance`` semantics — subclasses of listed types are also
            suppressed. Useful for expected framework errors (e.g. ``DependencyError``,
            ``HassetteError``) where a full traceback adds no diagnostic value.
            Defaults to ``()`` (no suppression — all exceptions include tracebacks).
        timeout: Deadline in seconds for the tracked body, or ``None`` for no deadline. Only
            this deadline expiring records ``TIMED_OUT``; a ``TimeoutError`` raised by the body
            itself (e.g. ``bus.wait_for`` or an HTTP client timeout) is recorded as ``ERROR``
            with a traceback, like any other exception.

    Usage::

        async with track_execution() as result:
            await do_work()
        # result.status == ExecutionStatus.SUCCESS, result.duration_ms populated

        async with track_execution(known_errors=(DependencyError,)) as result:
            await do_work()
        # DependencyError and its subclasses: result.error_traceback is None
        # Any other exception: result.error_traceback is the full traceback string
    """
    result = ExecutionResult()
    result.monotonic_start = time.monotonic()
    deadline = asyncio.timeout(timeout)
    try:
        async with deadline:
            yield result
        result.status = ExecutionStatus.SUCCESS
    except asyncio.CancelledError:
        result.status = ExecutionStatus.CANCELLED
        raise
    except Exception as exc:
        result.exc = exc
        result.error_type = type(exc).__name__
        if isinstance(exc, TimeoutError) and deadline.expired():
            # Only the framework's own deadline counts as a timeout; a TimeoutError raised by the
            # body (wait_for, HTTP clients) falls through to the error path below.
            result.status = ExecutionStatus.TIMED_OUT
            result.error_message = str(exc) if str(exc) else "execution timed out"
            raise
        result.status = ExecutionStatus.ERROR
        result.error_message = str(exc)
        result.is_di_failure = isinstance(exc, DependencyError)
        if known_errors and isinstance(exc, known_errors):
            result.error_traceback = None
        else:
            tb = traceback.format_exc()
            if len(tb) > MAX_TRACEBACK_SIZE:
                tb = tb[:MAX_TRACEBACK_SIZE] + TRACEBACK_TRUNCATION_SUFFIX
            result.error_traceback = tb
        raise
    finally:
        result.duration_ms = (time.monotonic() - result.monotonic_start) * 1000
