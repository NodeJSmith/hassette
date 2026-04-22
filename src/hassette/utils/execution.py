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

from hassette.exceptions import DependencyError

MAX_TRACEBACK_SIZE = 8192
"""Maximum traceback string length in characters. Tracebacks exceeding this are truncated."""


@dataclass
class ExecutionResult:
    """Captures timing and error information from a tracked execution."""

    monotonic_start: float = 0.0
    duration_ms: float = 0.0
    status: str = "pending"
    error_message: str | None = None
    error_type: str | None = None
    error_traceback: str | None = None
    is_di_failure: bool = False
    """True when the execution failed due to a DependencyError (or subclass)."""

    exc: BaseException | None = None
    """The exception raised during execution, or None if the execution succeeded or was cancelled.
    Populated for both ``Exception`` and ``TimeoutError`` — not for ``CancelledError``."""

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def is_error(self) -> bool:
        return self.status == "error"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def is_timed_out(self) -> bool:
        return self.status == "timed_out"


@asynccontextmanager
async def track_execution(
    known_errors: tuple[type[Exception], ...] = (),
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

    Usage::

        async with track_execution() as result:
            await do_work()
        # result.status == "success", result.duration_ms populated

        async with track_execution(known_errors=(DependencyError,)) as result:
            await do_work()
        # DependencyError and its subclasses: result.error_traceback is None
        # Any other exception: result.error_traceback is the full traceback string
    """
    result = ExecutionResult()
    result.monotonic_start = time.monotonic()
    try:
        yield result
        result.status = "success"
    except asyncio.CancelledError:
        result.status = "cancelled"
        raise
    except TimeoutError as exc:
        result.status = "timed_out"
        result.error_type = "TimeoutError"
        result.error_message = str(exc) if str(exc) else "execution timed out"
        result.exc = exc
        raise
    except Exception as exc:
        result.status = "error"
        result.error_message = str(exc)
        result.error_type = type(exc).__name__
        result.is_di_failure = isinstance(exc, DependencyError)
        result.exc = exc
        if known_errors and isinstance(exc, known_errors):
            result.error_traceback = None
        else:
            tb = traceback.format_exc()
            if len(tb) > MAX_TRACEBACK_SIZE:
                tb = tb[:MAX_TRACEBACK_SIZE] + "\n... [truncated]"
            result.error_traceback = tb
        raise
    finally:
        result.duration_ms = (time.monotonic() - result.monotonic_start) * 1000
