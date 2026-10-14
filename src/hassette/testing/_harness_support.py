"""Timeouts, wait helpers, and teardown/dispatch helpers used by the test harness."""

import asyncio
import contextlib
import inspect
import logging
import typing
from collections.abc import Awaitable, Callable, Generator
from typing import Any

from hassette.resources.base import Resource
from hassette.testing.config import WAIT_FOR_READY_TIMEOUT_SECONDS
from hassette.utils.func_utils import is_async_callable


# Do not use raw floats in harness code — reference these constants instead so
# any future re-tuning is a single-site edit.
class Timeouts:
    """Centralised timeout constants for the test harness.

    All values are in seconds. Rationale for each value is documented below.
    Changing a value here propagates everywhere the constant is used.
    """

    # How long HassetteHarness.start() waits for all children to become ready.
    # 5 s gives enough headroom for slow CI machines without masking real hangs.
    # Shared with hassette.testing._reset via WAIT_FOR_READY_TIMEOUT_SECONDS in
    # hassette.testing.config (that module, not this one, is the single source of truth —
    # see the comment there for why).
    WAIT_FOR_READY: float = WAIT_FOR_READY_TIMEOUT_SECONDS

    # How long seed_state() waits to acquire the StateProxy write lock.
    # Under test conditions the lock should never be contended for long; 5 s is
    # a generous upper bound that catches genuine deadlocks without false-positive
    # failures on slow machines.
    STATE_SEED_LOCK: float = 5.0


async def wait_for(
    predicate: Callable[[], bool] | Callable[[], typing.Awaitable[bool]],
    *,
    timeout: float = 3.0,
    interval: float = 0.02,
    desc: str = "condition",
) -> None:
    is_async = is_async_callable(predicate)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        result = (await predicate()) if is_async else predicate()  # pyright: ignore[reportGeneralTypeIssues]
        if result:
            return
        if loop.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for {desc}")
        await asyncio.sleep(interval)


async def shutdown_resource(res: Resource) -> None:
    await res.shutdown()


@contextlib.contextmanager
def collect_shutdown_errors(
    errors: list[Exception],
    exc_types: type[Exception] | tuple[type[Exception], ...] = Exception,
) -> Generator[None, None, None]:
    """Run the wrapped block, appending any matching exception to ``errors`` instead of raising.

    Used by ``HassetteHarness.stop()`` so a failure in one teardown step doesn't skip the rest —
    all collected errors are raised together as an ExceptionGroup once teardown finishes.
    """
    try:
        yield
    except exc_types as exc:
        errors.append(exc)


async def harness_dispatch(
    invoke_fn: Callable[[], Awaitable[None]],
    error_handler: Callable[..., Any] | None,
    make_error_context: Callable[[Exception], Any],
    log_label: str,
) -> None:
    """Shared dispatch logic for bus and scheduler harness stubs.

    The harness does NOT test timeout enforcement, task spawn isolation, or
    failure counter — those are covered by integration tests via real CommandExecutor.
    """
    if error_handler is None:
        await invoke_fn()
        return
    try:
        await invoke_fn()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        ctx = make_error_context(exc)
        try:
            result = error_handler(ctx)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logging.getLogger("hassette.testing._harness").warning(
                "Error handler raised during harness dispatch (%s)", log_label, exc_info=True
            )
