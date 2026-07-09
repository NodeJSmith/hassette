"""Unit tests for BusService._record_predicate_failure and dispatch predicate-error isolation."""

import time
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from hassette.bus.error_context import BusErrorContext
from hassette.core.bus_service import BusService
from hassette.events.base import Event
from hassette.test_utils.helpers import create_listener

if TYPE_CHECKING:
    from hassette.bus.listeners import Listener


def make_bus_service() -> tuple[BusService, MagicMock]:
    """Build a BusService with mocked dependencies for unit testing."""
    hassette = MagicMock()
    hassette.session_id = 42
    hassette.try_session_id.return_value = 42
    hassette.config.lifecycle.max_concurrent_dispatches = 10
    hassette.config.lifecycle.event_handler_timeout_seconds = 30.0
    hassette.config.logging.bus_service = "INFO"
    hassette.config.logging.all_events = False
    hassette.config.logging.all_hass_events = False
    hassette.config.logging.all_hassette_events = False
    hassette.config.bus_excluded_domains = []
    hassette.config.bus_excluded_entities = []

    executor = MagicMock()
    executor.enqueue_record = MagicMock()
    executor.invoke_error_handler = MagicMock()

    bs = object.__new__(BusService)
    bs.hassette = hassette
    bs._executor = executor
    bs.logger = MagicMock()
    bs.task_bucket = MagicMock()

    return bs, executor


def make_listener_with_error_handler(error_handler=None, app_resolver=None) -> "Listener":
    listener = create_listener(topic="test.pred", error_handler=error_handler)
    if app_resolver is not None:
        listener.invoker.set_app_error_handler_resolver(app_resolver)
    listener.mark_registered(99)
    return listener


class TestRecordPredicateFailure:
    def test_enqueues_error_record_with_correct_fields(self) -> None:
        bs, executor = make_bus_service()
        listener = make_listener_with_error_handler()
        event = Event(topic="test.pred", payload=SimpleNamespace())
        exc = ValueError("boom")

        start_ts = time.time()
        bs._record_predicate_failure(listener, "test.pred", event, exc, start_ts)

        executor.enqueue_record.assert_called_once()
        record = executor.enqueue_record.call_args[0][0]
        assert record.kind == "handler"
        assert record.status == "error"
        assert record.error_type == "ValueError"
        assert record.error_message == "boom"
        assert record.listener_id == 99
        assert record.session_id == 42
        assert record.execution_id is not None

    def test_session_id_fallback_on_runtime_error(self) -> None:
        bs, executor = make_bus_service()
        bs.hassette.try_session_id = MagicMock(return_value=None)

        listener = make_listener_with_error_handler()
        event = Event(topic="test.pred", payload=SimpleNamespace())

        bs._record_predicate_failure(listener, "test.pred", event, ValueError("x"), time.time())

        record = executor.enqueue_record.call_args[0][0]
        assert record.session_id is None

    def test_invokes_per_listener_error_handler(self) -> None:
        bs, _executor = make_bus_service()

        async def on_error(ctx: BusErrorContext) -> None:
            pass

        listener = make_listener_with_error_handler(error_handler=on_error)
        event = Event(topic="test.pred", payload=SimpleNamespace())

        bs._record_predicate_failure(listener, "test.pred", event, ValueError("x"), time.time())

        bs.task_bucket.spawn.assert_called_once()

    def test_invokes_app_level_error_handler_as_fallback(self) -> None:
        bs, _executor = make_bus_service()

        async def app_handler(ctx: BusErrorContext) -> None:
            pass

        listener = make_listener_with_error_handler(app_resolver=lambda: app_handler)
        event = Event(topic="test.pred", payload=SimpleNamespace())

        bs._record_predicate_failure(listener, "test.pred", event, ValueError("x"), time.time())

        bs.task_bucket.spawn.assert_called_once()

    def test_no_error_handler_skips_spawn(self) -> None:
        bs, _executor = make_bus_service()
        listener = make_listener_with_error_handler()
        event = Event(topic="test.pred", payload=SimpleNamespace())

        bs._record_predicate_failure(listener, "test.pred", event, ValueError("x"), time.time())

        bs.task_bucket.spawn.assert_not_called()


class TestDispatchPredicateRecordingIsolation:
    async def test_record_failure_caught_by_inner_try_except(self) -> None:
        """The inner try/except around _record_predicate_failure swallows its exceptions."""
        bs, _executor = make_bus_service()
        bs.router = MagicMock()
        bs._event_filter = MagicMock()
        bs._event_filter.should_skip.return_value = False
        bs._dispatch_semaphore = MagicMock()
        bs._dispatch_semaphore.locked.return_value = False
        bs._dispatch_semaphore.acquire = AsyncMock()
        bs._dispatch_pending = 0
        bs._dispatch_idle_event = MagicMock()

        def raising_pred(_ev: object) -> bool:
            raise ValueError("pred boom")

        listener = create_listener(where=raising_pred)
        bs.router.get_topic_listeners.return_value = [listener]
        event = Event(topic="test.pred", payload=SimpleNamespace())

        with (
            patch.object(bs, "_record_predicate_failure", side_effect=RuntimeError("record crash")),
            patch.object(bs, "expand_topics", return_value=["test.pred"]),
        ):
            await bs.dispatch("test.pred", event)

        bs.logger.exception.assert_any_call("Failed to record predicate failure for %s", listener)
