"""Unit tests for HandlerInvoker sub-struct.

These tests exercise the create/once-guard/invoke flow, not overlap behavior, so dispatch tests
use ``ExecutionMode.PARALLEL`` (the inline pass-through that never asks ``task_bucket`` to spawn a child).
``make_task_bucket`` is imported from the shared helpers so it stays in sync with the production
factory the integration tests rely on.
"""

import asyncio
from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from hassette_wire import ExecutionMode

from hassette import TaskBucket
from hassette.bus.listeners import HandlerInvoker, ListenerOptions
from hassette.types import BusErrorHandlerType, HandlerType
from tests.support.factories import make_hassette_event
from tests.support.helpers import make_task_bucket

TEST_EVENT = make_hassette_event()
"""The event every dispatch in this module runs for."""


async def simple_handler() -> None:
    """A simple async handler with no *args (valid DI signature)."""


def make_invoker(
    options: ListenerOptions | None = None,
    handler: HandlerType = simple_handler,
    kwargs: Mapping[str, Any] | None = None,
    task_bucket: TaskBucket | None = None,
    error_handler: BusErrorHandlerType | None = None,
    app_error_handler_resolver: Callable[[], BusErrorHandlerType | None] | None = None,
) -> HandlerInvoker:
    """Build a ``HandlerInvoker`` via ``HandlerInvoker.create()``, filling in sane defaults."""
    task_bucket = task_bucket if task_bucket is not None else make_task_bucket()
    options = options if options is not None else ListenerOptions()

    return HandlerInvoker.create(
        task_bucket=task_bucket,
        handler=handler,
        kwargs=kwargs,
        options=options,
        error_handler=error_handler,
        app_error_handler_resolver=app_error_handler_resolver,
    )


class TestHandlerInvokerCreate:
    def test_create_minimal(self) -> None:
        """HandlerInvoker.create() with a simple handler produces a functional invoker."""
        invoker = make_invoker()

        assert invoker.orig_handler is simple_handler
        assert invoker.kwargs is None
        assert invoker.error_handler is None
        assert invoker.app_error_handler_resolver is None
        assert invoker.rate_limiter is None
        assert invoker.options.once is False
        assert invoker.fired is False

    def test_create_keeps_options_reference(self) -> None:
        """HandlerInvoker.create() stores the ListenerOptions it was given."""
        options = ListenerOptions(once=True)
        invoker = make_invoker(options=options)

        assert invoker.options is options

    def test_create_with_debounce_builds_rate_limiter(self) -> None:
        """HandlerInvoker.create() with debounce builds a RateLimiter."""
        invoker = make_invoker(options=ListenerOptions(debounce=1.0))

        assert invoker.rate_limiter is not None

    def test_create_with_throttle_builds_rate_limiter(self) -> None:
        """HandlerInvoker.create() with throttle builds a RateLimiter."""
        invoker = make_invoker(options=ListenerOptions(throttle=2.0))

        assert invoker.rate_limiter is not None

    def test_create_without_rate_limiting_no_rate_limiter(self) -> None:
        """HandlerInvoker.create() without debounce/throttle leaves rate_limiter None."""
        invoker = make_invoker()

        assert invoker.rate_limiter is None

    def test_create_with_error_handler(self) -> None:
        error_handler = AsyncMock()

        invoker = make_invoker(error_handler=error_handler)

        assert invoker.error_handler is error_handler

    def test_create_with_kwargs(self) -> None:
        kwargs = {"my_key": "my_value"}

        invoker = make_invoker(kwargs=kwargs)

        assert invoker.kwargs == kwargs

    def test_has_slots(self) -> None:
        invoker = make_invoker()
        assert hasattr(type(invoker), "__slots__")


class TestHandlerInvokerMarkFired:
    def test_mark_fired_sets_flag(self) -> None:
        invoker = make_invoker()
        assert invoker.fired is False
        invoker.mark_fired()
        assert invoker.fired is True

    def test_mark_fired_idempotent(self) -> None:
        invoker = make_invoker()
        invoker.mark_fired()
        invoker.mark_fired()
        assert invoker.fired is True


class TestHandlerInvokerAppErrorHandlerResolver:
    def test_create_with_resolver(self) -> None:
        resolver = MagicMock(return_value=None)
        invoker = make_invoker(app_error_handler_resolver=resolver)
        assert invoker.app_error_handler_resolver is resolver


class TestHandlerInvokerDispatch:
    # These tests exercise the once-guard + invoke flow, not overlap behavior. They use
    # ``ExecutionMode.PARALLEL`` (the byte-for-byte inline pass-through) so the MagicMock task_bucket
    # is never asked to spawn a real child task. Overlap-mode dispatch is covered by the
    # ExecutionModeGuard unit tests and the bus integration tests.
    async def test_dispatch_calls_invoke_fn(self) -> None:
        invoker = make_invoker(options=ListenerOptions(mode=ExecutionMode.PARALLEL))
        invoke_fn = AsyncMock()
        await invoker.dispatch(TEST_EVENT, invoke_fn, lambda: None)
        invoke_fn.assert_awaited_once()

    async def test_dispatch_once_guard_prevents_double_fire(self) -> None:
        """Once-guard: if once=True and fired=True, dispatch is skipped."""
        invoker = make_invoker(options=ListenerOptions(once=True, mode=ExecutionMode.PARALLEL))
        invoke_fn = AsyncMock()

        # First dispatch — should fire and mark fired
        await invoker.dispatch(TEST_EVENT, invoke_fn, lambda: None)
        invoke_fn.assert_awaited_once()

        # Second dispatch — should be skipped
        invoke_fn.reset_mock()
        await invoker.dispatch(TEST_EVENT, invoke_fn, lambda: None)
        invoke_fn.assert_not_awaited()

    async def test_dispatch_once_false_allows_multiple(self) -> None:
        """once=False allows multiple dispatches."""
        invoker = make_invoker(options=ListenerOptions(once=False, mode=ExecutionMode.PARALLEL))
        invoke_fn = AsyncMock()
        await invoker.dispatch(TEST_EVENT, invoke_fn, lambda: None)
        await invoker.dispatch(TEST_EVENT, invoke_fn, lambda: None)
        assert invoke_fn.await_count == 2

    async def test_dispatch_skipped_when_already_fired(self) -> None:
        """If fired is True before dispatch, dispatch returns immediately."""
        invoker = make_invoker(options=ListenerOptions(once=True))
        invoker.mark_fired()
        invoke_fn = AsyncMock()
        await invoker.dispatch(TEST_EVENT, invoke_fn, lambda: None)
        invoke_fn.assert_not_awaited()


class TestHandlerInvokerInvoke:
    async def test_invoke_calls_handler(self) -> None:
        called = False

        async def handler() -> None:
            nonlocal called
            called = True

        invoker = make_invoker(handler=handler)

        mock_event = MagicMock()
        await invoker.invoke(mock_event)
        assert called

    async def test_invoke_passes_extra_kwargs(self) -> None:
        received = {}

        async def handler(extra: str = "") -> None:
            received["extra"] = extra

        invoker = make_invoker(handler=handler, kwargs={"extra": "hello"})

        mock_event = MagicMock()
        await invoker.invoke(mock_event)
        assert received["extra"] == "hello"


class TestHandlerInvokerWarnStalled:
    """Tests for the stall watchdog wired through run_with_mode -> run_through_guard.

    ``ExecutionMode.PARALLEL`` awaits inline and never arms the watchdog, so these tests use
    ``ExecutionMode.SINGLE`` (a real task_bucket spawn is required for the watchdog's
    ``call_later`` to race against the handler).
    """

    async def test_warn_stalled_fires_when_handler_exceeds_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A handler that runs past STALL_THRESHOLD_SECONDS triggers warn_stalled(threshold).

        Wraps (not replaces) the real method so its actual body — the LOGGER.warning call —
        still runs; the wrapper only records the call for the assertion.
        """
        monkeypatch.setattr("hassette.execution_mode.STALL_THRESHOLD_SECONDS", 0.01)
        warn_calls: list[float] = []
        original_warn_stalled = HandlerInvoker.warn_stalled

        def spy_warn_stalled(self: HandlerInvoker, threshold: float, effective_timeout: float | None) -> None:
            warn_calls.append(threshold)
            original_warn_stalled(self, threshold, effective_timeout)

        monkeypatch.setattr(HandlerInvoker, "warn_stalled", spy_warn_stalled)

        invoker = make_invoker(options=ListenerOptions(mode=ExecutionMode.SINGLE))

        async def slow_invoke() -> None:
            await asyncio.sleep(0.2)

        await invoker.dispatch(TEST_EVENT, slow_invoke, lambda: None)

        assert warn_calls == [0.01], "warn_stalled should fire once, with the patched threshold"

    async def test_warn_stalled_not_called_when_handler_finishes_quickly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A handler that finishes well under the threshold never triggers the watchdog."""
        monkeypatch.setattr("hassette.execution_mode.STALL_THRESHOLD_SECONDS", 5.0)
        warn_calls: list[float] = []

        def spy_warn_stalled(_self: HandlerInvoker, threshold: float, _effective_timeout: float | None) -> None:
            warn_calls.append(threshold)

        monkeypatch.setattr(HandlerInvoker, "warn_stalled", spy_warn_stalled)

        invoker = make_invoker(options=ListenerOptions(mode=ExecutionMode.SINGLE))

        async def fast_invoke() -> None:
            return

        await invoker.dispatch(TEST_EVENT, fast_invoke, lambda: None)

        assert warn_calls == []

    def test_warn_stalled_names_the_threshold_source(self, caplog: pytest.LogCaptureFixture) -> None:
        """The WARNING says why it fired at this threshold."""
        invoker = make_invoker(options=ListenerOptions(mode=ExecutionMode.SINGLE, timeout=300.0))

        with caplog.at_level("WARNING", logger="hassette.bus.listeners"):
            invoker.warn_stalled(240.0, 300.0)

        assert "for over 240s (80% of its 300s timeout) and is still running" in caplog.text
