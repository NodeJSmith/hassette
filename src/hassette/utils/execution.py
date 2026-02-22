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


@dataclass
class ExecutionResult:
    """Captures timing and error information from a tracked execution."""

    monotonic_start: float = 0.0
    duration_ms: float = 0.0
    status: str = "pending"
    error_message: str | None = None
    error_type: str | None = None
    error_traceback: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def is_error(self) -> bool:
        return self.status == "error"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"


@asynccontextmanager
async def track_execution() -> AsyncIterator[ExecutionResult]:
    """Async context manager that tracks execution timing and errors.

    Yields an ExecutionResult that is populated on exit. Always re-raises exceptions.

    Usage::

        async with track_execution() as result:
            await do_work()
        # result.status == "success", result.duration_ms populated
    """
    result = ExecutionResult()
    result.monotonic_start = time.monotonic()
    try:
        yield result
        result.status = "success"
    except asyncio.CancelledError:
        result.status = "cancelled"
        raise
    except Exception as exc:
        result.status = "error"
        result.error_message = str(exc)
        result.error_type = type(exc).__name__
        result.error_traceback = traceback.format_exc()
        raise
    finally:
        result.duration_ms = (time.monotonic() - result.monotonic_start) * 1000
