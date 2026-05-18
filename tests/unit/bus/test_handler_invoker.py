"""Unit tests for HandlerInvoker sub-struct."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.listeners import HandlerInvoker, ListenerOptions


def _make_task_bucket() -> MagicMock:
    tb = MagicMock()
    tb.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    return tb


async def _simple_handler() -> None:
    """A simple async handler with no *args (valid DI signature)."""


class TestHandlerInvokerCreate:
    def test_create_minimal(self) -> None:
        """HandlerInvoker.create() with a simple handler produces a functional invoker."""
        task_bucket = _make_task_bucket()
        options = ListenerOptions()

        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=options,
        )

        assert invoker.orig_handler is _simple_handler
        assert invoker.kwargs is None
        assert invoker.error_handler is None
        assert invoker._app_error_handler_resolver is None
        assert invoker._rate_limiter is None
        assert invoker.once is False
        assert invoker._fired is False

    def test_create_copies_once_from_options(self) -> None:
        """HandlerInvoker.create() copies once=True from ListenerOptions."""
        task_bucket = _make_task_bucket()
        options = ListenerOptions(once=True)

        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=options,
        )

        assert invoker.once is True

    def test_create_with_debounce_builds_rate_limiter(self) -> None:
        """HandlerInvoker.create() with debounce builds a RateLimiter."""
        task_bucket = _make_task_bucket()
        options = ListenerOptions(debounce=1.0)

        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=options,
        )

        assert invoker._rate_limiter is not None

    def test_create_with_throttle_builds_rate_limiter(self) -> None:
        """HandlerInvoker.create() with throttle builds a RateLimiter."""
        task_bucket = _make_task_bucket()
        options = ListenerOptions(throttle=2.0)

        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=options,
        )

        assert invoker._rate_limiter is not None

    def test_create_without_rate_limiting_no_rate_limiter(self) -> None:
        """HandlerInvoker.create() without debounce/throttle leaves _rate_limiter None."""
        task_bucket = _make_task_bucket()
        options = ListenerOptions()

        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=options,
        )

        assert invoker._rate_limiter is None

    def test_create_with_error_handler(self) -> None:
        task_bucket = _make_task_bucket()
        error_handler = AsyncMock()
        options = ListenerOptions()

        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=options,
            error_handler=error_handler,
        )

        assert invoker.error_handler is error_handler

    def test_create_with_kwargs(self) -> None:
        task_bucket = _make_task_bucket()
        options = ListenerOptions()
        kwargs = {"my_key": "my_value"}

        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=kwargs,
            options=options,
        )

        assert invoker.kwargs == kwargs

    def test_create_with_mock_task_bucket(self) -> None:
        """AC#4: HandlerInvoker.create() can be called with a MagicMock task_bucket."""
        task_bucket = MagicMock()
        task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
        options = ListenerOptions()

        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=options,
        )

        assert invoker is not None
        assert invoker._fired is False

    def test_has_slots(self) -> None:
        task_bucket = _make_task_bucket()
        options = ListenerOptions()
        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=options,
        )
        assert hasattr(type(invoker), "__slots__")


class TestHandlerInvokerMarkFired:
    def test_mark_fired_sets_flag(self) -> None:
        task_bucket = _make_task_bucket()
        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=ListenerOptions(),
        )
        assert invoker._fired is False
        invoker.mark_fired()
        assert invoker._fired is True

    def test_mark_fired_idempotent(self) -> None:
        task_bucket = _make_task_bucket()
        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=ListenerOptions(),
        )
        invoker.mark_fired()
        invoker.mark_fired()
        assert invoker._fired is True


class TestHandlerInvokerSetAppErrorHandlerResolver:
    def test_set_resolver(self) -> None:
        task_bucket = _make_task_bucket()
        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=ListenerOptions(),
        )
        resolver = MagicMock(return_value=None)
        invoker.set_app_error_handler_resolver(resolver)
        assert invoker._app_error_handler_resolver is resolver


class TestHandlerInvokerDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_calls_invoke_fn(self) -> None:
        task_bucket = _make_task_bucket()
        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=ListenerOptions(),
        )
        invoke_fn = AsyncMock()
        await invoker.dispatch(invoke_fn)
        invoke_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_once_guard_prevents_double_fire(self) -> None:
        """Once-guard: if once=True and _fired=True, dispatch is skipped."""
        task_bucket = _make_task_bucket()
        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=ListenerOptions(once=True),
        )
        invoke_fn = AsyncMock()

        # First dispatch — should fire and mark fired
        await invoker.dispatch(invoke_fn)
        invoke_fn.assert_awaited_once()

        # Second dispatch — should be skipped
        invoke_fn.reset_mock()
        await invoker.dispatch(invoke_fn)
        invoke_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dispatch_once_false_allows_multiple(self) -> None:
        """once=False allows multiple dispatches."""
        task_bucket = _make_task_bucket()
        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=ListenerOptions(once=False),
        )
        invoke_fn = AsyncMock()
        await invoker.dispatch(invoke_fn)
        await invoker.dispatch(invoke_fn)
        assert invoke_fn.await_count == 2

    @pytest.mark.asyncio
    async def test_dispatch_skipped_when_already_fired(self) -> None:
        """If _fired is True before dispatch, dispatch returns immediately."""
        task_bucket = _make_task_bucket()
        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=_simple_handler,
            kwargs=None,
            options=ListenerOptions(once=True),
        )
        invoker.mark_fired()
        invoke_fn = AsyncMock()
        await invoker.dispatch(invoke_fn)
        invoke_fn.assert_not_awaited()


class TestHandlerInvokerInvoke:
    @pytest.mark.asyncio
    async def test_invoke_calls_handler(self) -> None:
        called = False

        async def handler() -> None:
            nonlocal called
            called = True

        task_bucket = _make_task_bucket()
        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=handler,
            kwargs=None,
            options=ListenerOptions(),
        )

        mock_event = MagicMock()
        await invoker.invoke(mock_event)
        assert called

    @pytest.mark.asyncio
    async def test_invoke_passes_extra_kwargs(self) -> None:
        received = {}

        async def handler(extra: str = "") -> None:
            received["extra"] = extra

        task_bucket = _make_task_bucket()
        invoker = HandlerInvoker.create(
            task_bucket=task_bucket,
            handler=handler,
            kwargs={"extra": "hello"},
            options=ListenerOptions(),
        )

        mock_event = MagicMock()
        await invoker.invoke(mock_event)
        assert received["extra"] == "hello"
