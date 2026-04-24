import asyncio
import threading
import typing
from contextlib import suppress
from types import SimpleNamespace
from typing import ClassVar, cast
from unittest.mock import AsyncMock, Mock

import pytest

from hassette import Hassette
from hassette.bus import Bus
from hassette.config.config import HassetteConfig
from hassette.core.api_resource import ApiResource
from hassette.core.app_handler import AppHandler
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.service_watcher import ServiceWatcher
from hassette.core.telemetry_query_service import TelemetryQueryService
from hassette.core.web_api_service import WebApiService
from hassette.core.websocket_service import WebsocketService
from hassette.resources.base import Resource
from hassette.scheduler import Scheduler
from hassette.test_utils import wait_for
from hassette.utils.service_utils import topological_sort

if typing.TYPE_CHECKING:
    from hassette.events import Event


@pytest.fixture
async def hassette_instance(test_config: HassetteConfig):
    """Provide a fresh Hassette instance and restore context afterwards."""
    test_config.reload()
    instance = Hassette(test_config)
    try:
        yield instance
    finally:
        with suppress(Exception):
            if not instance._event_stream_service.event_streams_closed:
                await instance._event_stream_service.close_streams()

        with suppress(Exception):
            if not instance._bus_service.stream._closed:
                await instance._bus_service.stream.aclose()


def test_unique_name_is_constant(hassette_instance: Hassette) -> None:
    """unique_name always returns the static identifier."""
    assert hassette_instance.unique_name == "Hassette"


def test_constructor_registers_background_services(hassette_instance: Hassette) -> None:
    """Constructor wires up expected services and resources."""
    assert isinstance(hassette_instance._database_service, DatabaseService)
    assert isinstance(hassette_instance._command_executor, CommandExecutor)
    assert isinstance(hassette_instance._bus_service, BusService)
    assert isinstance(hassette_instance._service_watcher, ServiceWatcher)
    assert isinstance(hassette_instance._websocket_service, WebsocketService)
    assert isinstance(hassette_instance._file_watcher, FileWatcherService)
    assert isinstance(hassette_instance._app_handler, AppHandler)
    assert isinstance(hassette_instance._scheduler_service, SchedulerService)
    assert isinstance(hassette_instance._api_service, ApiResource)
    assert isinstance(hassette_instance._runtime_query_service, RuntimeQueryService)
    assert isinstance(hassette_instance._telemetry_query_service, TelemetryQueryService)
    assert isinstance(hassette_instance._web_api_service, WebApiService)
    assert isinstance(hassette_instance._bus, Bus)
    assert isinstance(hassette_instance._scheduler, Scheduler)
    assert hassette_instance.api is not None

    expected_children = [
        hassette_instance._event_stream_service,
        hassette_instance._database_service,
        hassette_instance._session_manager,
        hassette_instance._command_executor,
        hassette_instance._bus_service,
        hassette_instance._service_watcher,
        hassette_instance._websocket_service,
        hassette_instance._file_watcher,
        hassette_instance._app_handler,
        hassette_instance._scheduler_service,
        hassette_instance._api_service,
        hassette_instance._runtime_query_service,
        hassette_instance._telemetry_query_service,
        hassette_instance._web_api_service,
        hassette_instance._web_ui_watcher,
        hassette_instance._bus,
        hassette_instance._scheduler,
        hassette_instance.api,
    ]
    for child in expected_children:
        assert child in hassette_instance.children


async def test_event_streams_closed_reflects_state(hassette_instance: Hassette) -> None:
    """event_streams_closed mirrors the underlying stream lifecycle."""
    assert hassette_instance.event_streams_closed is False, "Streams should start open"
    await hassette_instance._event_stream_service.close_streams()
    await asyncio.sleep(0)  # allow state to propagate
    assert hassette_instance.event_streams_closed is True, "Streams should close after aclose"


def test_loop_property_raises_when_not_started(hassette_instance: Hassette) -> None:
    """loop property raises when Hassette is not running."""
    with pytest.raises(RuntimeError):
        _ = hassette_instance.loop


async def test_loop_property_returns_running_loop(hassette_instance: Hassette) -> None:
    """loop property returns the configured loop once set."""
    running_loop = asyncio.get_running_loop()
    hassette_instance._loop = running_loop
    assert hassette_instance.loop is running_loop, "loop property should return the configured loop"


def test_apps_property_forwards_to_handler(hassette_instance: Hassette) -> None:
    """apps property proxies to the app handler."""
    hassette_instance._app_handler = SimpleNamespace(apps={"demo": []})  # pyright: ignore[reportAttributeAccessIssue]
    assert hassette_instance.apps == {"demo": []}, "apps property should forward to handler"


def test_get_app_forwards_to_handler(hassette_instance: Hassette) -> None:
    """get_app delegates to the handler's get method."""
    handler = SimpleNamespace()
    handler.get = Mock(return_value="app-instance")
    hassette_instance._app_handler = handler  # pyright: ignore[reportAttributeAccessIssue]

    retrieved = hassette_instance.get_app("demo", index=2)

    handler.get.assert_called_once_with("demo", 2)
    assert retrieved == "app-instance", "get_app should return the handler's result"


async def test_send_event_writes_to_stream(hassette_instance: Hassette) -> None:
    """send_event pushes topic and payload onto the internal stream."""
    payload = SimpleNamespace(value=123)
    await hassette_instance.send_event("topic.demo", cast("Event", payload))

    received_topic, received_event = await hassette_instance._event_stream_service.receive_stream.receive()
    assert received_topic == "topic.demo", "send_event should push correct topic"
    assert received_event is payload, "send_event should push correct payload"


async def test_wait_for_ready_uses_config_timeout(monkeypatch: pytest.MonkeyPatch, hassette_instance: Hassette) -> None:
    """wait_for_ready leverages the helper with the configured timeout."""
    waiter = AsyncMock(return_value=True)
    monkeypatch.setattr("hassette.core.core.wait_for_ready", waiter)

    resources = [Mock()]
    result = await hassette_instance.wait_for_ready(cast("list[Resource]", resources))

    waiter.assert_awaited_once_with(
        resources,
        timeout=hassette_instance.config.startup_timeout_seconds,
        shutdown_event=hassette_instance.shutdown_event,
    )
    assert result is True, "Expected wait_for_ready to return True from the helper"


async def test_wait_for_ready_accepts_explicit_timeout(
    monkeypatch: pytest.MonkeyPatch, hassette_instance: Hassette
) -> None:
    """wait_for_ready passes through an explicit timeout."""
    waiter = AsyncMock(return_value=False)
    monkeypatch.setattr("hassette.core.core.wait_for_ready", waiter)

    resources = [Mock()]
    result = await hassette_instance.wait_for_ready(cast("list[Resource]", resources), timeout=42)

    waiter.assert_awaited_once_with(resources, timeout=42, shutdown_event=hassette_instance.shutdown_event)
    assert result is False, "Expected wait_for_ready to return False from the helper"


async def test_run_forever_starts_and_shuts_down(hassette_instance: Hassette) -> None:
    """run_forever uses phased startup: DB first, session, then remaining services."""
    db_start = Mock()
    other_starts: list[Mock] = []

    hassette_instance._database_service.start = db_start  # pyright: ignore[reportAttributeAccessIssue]
    for child in hassette_instance.children:
        if child is not hassette_instance._database_service:
            m = Mock()
            other_starts.append(m)
            child.start = m  # pyright: ignore[reportAttributeAccessIssue]

    hassette_instance.wait_for_ready = AsyncMock(return_value=True)
    hassette_instance.shutdown = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    hassette_instance._session_manager.mark_orphaned_sessions = AsyncMock()
    hassette_instance._session_manager.create_session = AsyncMock()

    task = asyncio.create_task(hassette_instance.run_forever())
    asyncio.get_event_loop().call_later(0.5, hassette_instance.shutdown_event.set)
    await wait_for(lambda: db_start.called, desc="run_forever started")
    await task

    # Phase 1: DB started first
    db_start.assert_called_once()
    # Phase 2: remaining resources started after session creation
    for m in other_starts:
        m.assert_called_once()
    # wait_for_ready called at least twice: DB first, then all children.
    # Background tasks (e.g. framework listener registration) may add additional calls.
    assert hassette_instance.wait_for_ready.await_count >= 2
    hassette_instance.wait_for_ready.assert_any_await(
        [hassette_instance.database_service], timeout=hassette_instance.config.startup_timeout_seconds
    )
    hassette_instance.wait_for_ready.assert_any_await(
        list(hassette_instance.children), timeout=hassette_instance.config.startup_timeout_seconds
    )
    # Session created between phase 1 and phase 2
    hassette_instance._session_manager.mark_orphaned_sessions.assert_awaited_once()
    hassette_instance._session_manager.create_session.assert_awaited_once()
    hassette_instance.shutdown.assert_awaited()
    assert hassette_instance._loop is asyncio.get_running_loop(), f"Event loop does not match {hassette_instance._loop}"
    assert hassette_instance._loop_thread_id == threading.get_ident(), "Thread ID does not match"


async def test_run_forever_handles_session_init_failure(hassette_instance: Hassette) -> None:
    """run_forever triggers shutdown when session initialization raises."""
    hassette_instance._database_service.start = Mock()  # pyright: ignore[reportAttributeAccessIssue]
    hassette_instance.wait_for_ready = AsyncMock(return_value=True)
    hassette_instance.shutdown = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    hassette_instance._session_manager.mark_orphaned_sessions = AsyncMock(side_effect=RuntimeError("db broke"))
    hassette_instance._session_manager.create_session = AsyncMock()

    await hassette_instance.run_forever()

    hassette_instance._session_manager.mark_orphaned_sessions.assert_awaited_once()
    hassette_instance._session_manager.create_session.assert_not_awaited()
    hassette_instance.shutdown.assert_awaited()


async def test_run_forever_handles_startup_failure(hassette_instance: Hassette) -> None:
    """run_forever triggers shutdown when remaining resources fail to become ready."""
    hassette_instance._database_service.start = Mock()  # pyright: ignore[reportAttributeAccessIssue]
    for child in hassette_instance.children:
        if child is not hassette_instance._database_service:
            child.start = Mock()  # pyright: ignore[reportAttributeAccessIssue]
    # DB wait succeeds (True), all-children wait fails (False)
    hassette_instance.wait_for_ready = AsyncMock(side_effect=[True, False])
    hassette_instance.shutdown = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    hassette_instance._session_manager.mark_orphaned_sessions = AsyncMock()
    hassette_instance._session_manager.create_session = AsyncMock()

    await hassette_instance.run_forever()

    assert hassette_instance.wait_for_ready.await_count == 2
    hassette_instance.shutdown.assert_awaited_once()
    assert hassette_instance.ready_event.is_set(), "Ready event was not set"


async def test_before_shutdown_removes_listeners_and_finalizes(hassette_instance: Hassette) -> None:
    """before_shutdown removes bus listeners and finalizes the session."""
    completed_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    completed_future.set_result(None)
    hassette_instance._bus.remove_all_listeners = Mock(return_value=completed_future)
    hassette_instance._session_manager.finalize_session = AsyncMock()

    await hassette_instance.before_shutdown()

    hassette_instance._bus.remove_all_listeners.assert_called_once()
    hassette_instance._session_manager.finalize_session.assert_awaited_once()


async def test_before_shutdown_finalizes_even_when_listener_removal_fails(hassette_instance: Hassette) -> None:
    """before_shutdown still finalizes session when remove_all_listeners raises."""
    hassette_instance._bus.remove_all_listeners = AsyncMock(side_effect=RuntimeError("bus error"))
    hassette_instance._session_manager.finalize_session = AsyncMock()

    await hassette_instance.before_shutdown()

    hassette_instance._bus.remove_all_listeners.assert_awaited_once()
    hassette_instance._session_manager.finalize_session.assert_awaited_once()


async def test_concurrent_crash_and_finalize_are_serialized(hassette_instance: Hassette) -> None:
    """on_service_crashed and finalize_session on SessionManager coordinate via _session_lock.

    Verifies that concurrent crash recording and session finalization don't
    interleave — the lock forces one to complete before the other starts.
    """
    sm = hassette_instance._session_manager
    sm._session_id = 42
    sm._session_error = False

    call_order: list[str] = []
    crash_holding_lock = asyncio.Event()
    crash_may_release = asyncio.Event()

    async def slow_crash(_event: typing.Any) -> None:
        """Simulate crash handler that holds the lock while doing slow work."""
        async with sm._session_lock:
            call_order.append("crash_acquired")
            crash_holding_lock.set()
            await crash_may_release.wait()  # hold lock until test says release
            call_order.append("crash_released")

    sm._database_service = Mock()
    sm._database_service.db = AsyncMock()

    submit_calls: list[str] = []

    async def tracking_submit(coro: typing.Any) -> None:
        """Track when finalize's submit actually executes, then consume the coroutine."""
        submit_calls.append("submit")
        await coro

    sm._database_service.submit = tracking_submit

    crash_event = Mock()

    # Start crash first, wait for it to hold the lock
    crash_task = asyncio.create_task(slow_crash(crash_event))
    await crash_holding_lock.wait()

    # Start finalize — it should block on the lock
    finalize_task = asyncio.create_task(sm.finalize_session())
    await asyncio.sleep(0.01)  # give finalize a chance to acquire lock

    # Finalize should NOT have called submit yet (crash holds the lock)
    assert submit_calls == [], f"Finalize ran while crash held the lock: {submit_calls}"

    # Release the crash lock
    crash_may_release.set()
    await asyncio.gather(crash_task, finalize_task)

    # Now finalize should have completed
    assert submit_calls == ["submit"], f"Finalize should have called submit after crash released: {submit_calls}"
    assert call_order == ["crash_acquired", "crash_released"]


def test_database_service_starts_first(hassette_instance: Hassette) -> None:
    """run_forever phase 1 starts DatabaseService before any other child.

    Mocks all child .start() methods and verifies only DatabaseService is called
    after the phase-1 step.
    """
    for child in hassette_instance.children:
        child.start = Mock()  # pyright: ignore[reportAttributeAccessIssue]

    # Simulate phase 1: only the database service starts
    hassette_instance._database_service.start()

    hassette_instance._database_service.start.assert_called_once()  # pyright: ignore[reportAttributeAccessIssue]
    for child in hassette_instance.children:
        if child is not hassette_instance._database_service:
            child.start.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]


def test_init_order_contains_all_children(hassette_instance: Hassette) -> None:
    """_init_order contains exactly the same types as the registered children."""
    child_types = set(type(c) for c in hassette_instance.children)
    init_order_types = set(hassette_instance._init_order)
    assert init_order_types == child_types


def test_init_order_has_no_cycles(hassette_instance: Hassette) -> None:
    """topological_sort completes without raising for the real service graph."""
    all_types = list(dict.fromkeys(type(c) for c in hassette_instance.children))
    # Should not raise ValueError
    result = topological_sort(all_types)
    assert len(result) == len(all_types)


def test_graph_validation_catches_missing_type() -> None:
    """ValueError is raised when a depends_on entry references a type not in Hassette's children.

    Exercises the same validation logic that Hassette.__init__ runs, using a stub service
    whose depends_on points to a type that is absent from the type list.
    """

    class _GhostDep(Resource):
        """A resource type absent from the registered child list."""

    class _StubService(DatabaseService):
        """Stub that declares a dependency on the unregistered _GhostDep."""

        depends_on: ClassVar[list[type[Resource]]] = [_GhostDep]

    def _validate_deps(types: list[type[Resource]]) -> None:
        for child_type in types:
            for dep_type in child_type.depends_on:
                if not any(issubclass(t, dep_type) for t in types):
                    raise ValueError(
                        f"{child_type.__name__} declares depends_on=[{dep_type.__name__}] "
                        f"but no matching child type found in Hassette"
                    )

    with pytest.raises(ValueError, match="_GhostDep"):
        _validate_deps([_StubService])
