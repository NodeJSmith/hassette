import asyncio
import inspect
import threading
import typing
from types import SimpleNamespace
from typing import ClassVar, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest

import hassette.core.block_io_guard as block_io_guard
import hassette.core.core as core_module
from hassette import Hassette
from hassette.api import Api
from hassette.bus import Bus
from hassette.core.api_resource import ApiResource
from hassette.core.app_handler import AppHandler
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.event_stream_service import EventStreamService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.logging_service import LoggingService
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.service_watcher import ServiceWatcher
from hassette.core.session_manager import SessionManager
from hassette.core.state_proxy import StateProxy
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.core.web_api_service import WebApiService
from hassette.core.web_ui_watcher import WebUiWatcherService
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import FatalError
from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.scheduler import Scheduler
from hassette.state_manager import StateManager
from hassette.test_utils import wait_for
from hassette.utils.service_utils import topological_sort, validate_dependency_graph

if typing.TYPE_CHECKING:
    from hassette.events import Event


def test_unique_name_is_constant(hassette_instance: Hassette) -> None:
    """unique_name always returns the static identifier."""
    assert hassette_instance.unique_name == "Hassette"


def test_constructor_registers_background_services(hassette_instance: Hassette) -> None:
    """Constructor wires up exactly the expected set of background services and resources."""
    child_types = {type(c) for c in hassette_instance.children}

    expected_types = {
        SyncExecutorService,
        EventStreamService,
        DatabaseService,
        LoggingService,
        CommandExecutor,
        BusService,
        SchedulerService,
        SessionManager,
        ServiceWatcher,
        WebsocketService,
        FileWatcherService,
        WebUiWatcherService,
        AppHandler,
        ApiResource,
        StateProxy,
        RuntimeQueryService,
        TelemetryQueryService,
        WebApiService,
        Bus,
        Scheduler,
        StateManager,
        Api,
    }

    assert child_types == expected_types
    assert hassette_instance.api is not None


async def test_event_streams_closed_reflects_state(hassette_instance: Hassette) -> None:
    """event_streams_closed mirrors the underlying stream lifecycle."""
    assert hassette_instance.event_streams_closed is False, "Streams should start open"
    await hassette_instance.event_stream_service.close_streams()
    await asyncio.sleep(0)  # allow state to propagate
    assert hassette_instance.event_streams_closed is True, "Streams should close after aclose"


def test_loop_property_raises_when_not_started(hassette_instance: Hassette) -> None:
    """Loop property raises when Hassette is not running."""
    with pytest.raises(RuntimeError):
        _ = hassette_instance.loop


async def test_loop_property_returns_running_loop(hassette_instance: Hassette) -> None:
    """Loop property returns the configured loop once set."""
    running_loop = asyncio.get_running_loop()
    hassette_instance._loop = running_loop  # coordinator-internal
    assert hassette_instance.loop is running_loop, "loop property should return the configured loop"


def test_apps_property_forwards_to_handler(hassette_instance: Hassette) -> None:
    """Apps property proxies to the app handler."""
    app_handler = SimpleNamespace(apps={"demo": []})
    hassette_instance._app_handler = app_handler  # pyright: ignore[reportAttributeAccessIssue]  # coordinator-internal
    assert hassette_instance.apps == {"demo": []}, "apps property should forward to handler"


def test_get_app_forwards_to_handler(hassette_instance: Hassette) -> None:
    """get_app delegates to the handler's get method."""
    handler = SimpleNamespace()
    handler.get = Mock(return_value="app-instance")
    hassette_instance._app_handler = handler  # pyright: ignore[reportAttributeAccessIssue]  # coordinator-internal

    retrieved = hassette_instance.get_app("demo", index=2)

    handler.get.assert_called_once_with("demo", 2)
    assert retrieved == "app-instance", "get_app should return the handler's result"


async def test_send_event_writes_to_stream(hassette_instance: Hassette) -> None:
    """send_event pushes the event onto the internal stream."""
    payload = SimpleNamespace(topic="topic.demo", value=123)
    await hassette_instance.send_event(cast("Event", payload))

    received_event = await hassette_instance.event_stream_service.receive_stream.receive()
    assert received_event is payload, "send_event should push the event object"
    assert received_event.topic == "topic.demo", "event should carry its topic"


async def test_wait_for_ready_uses_config_timeout(monkeypatch: pytest.MonkeyPatch, hassette_instance: Hassette) -> None:
    """wait_for_ready calls the helper with the configured timeout."""
    waiter = AsyncMock(return_value=True)
    monkeypatch.setattr("hassette.core.core.wait_for_ready", waiter)

    resources = [Mock()]
    result = await hassette_instance.wait_for_ready(cast("list[Resource]", resources))

    waiter.assert_awaited_once_with(
        resources,
        timeout=hassette_instance.config.lifecycle.startup_timeout_seconds,
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
    """run_forever uses phased startup: DB first, session, then wave-based remaining services."""
    db_start = Mock()
    other_starts: list[Mock] = []

    hassette_instance.database_service.start = db_start  # pyright: ignore[reportAttributeAccessIssue]
    for child in hassette_instance.children:
        if child is not hassette_instance.database_service:
            m = Mock()
            other_starts.append(m)
            child.start = m  # pyright: ignore[reportAttributeAccessIssue]

    hassette_instance.wait_for_ready = AsyncMock(return_value=True)
    hassette_instance.shutdown = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    hassette_instance.session_manager.mark_orphaned_sessions = AsyncMock()
    hassette_instance.session_manager.create_session = AsyncMock()

    task = asyncio.create_task(hassette_instance.run_forever())
    asyncio.get_event_loop().call_later(0.5, hassette_instance.shutdown_event.set)
    await wait_for(lambda: db_start.called, desc="run_forever started")
    await task

    # Phase 1: DB started first
    db_start.assert_called_once()
    # Phase 2: remaining resources started after session creation (wave-by-wave)
    for m in other_starts:
        m.assert_called_once()
    # wait_for_ready called: once for DB, then once per startup wave.
    assert hassette_instance.wait_for_ready.await_count >= 2
    hassette_instance.wait_for_ready.assert_any_await(
        [hassette_instance.database_service], timeout=hassette_instance.config.lifecycle.startup_timeout_seconds
    )
    # Session created between phase 1 and phase 2
    hassette_instance.session_manager.mark_orphaned_sessions.assert_awaited_once()
    hassette_instance.session_manager.create_session.assert_awaited_once()
    hassette_instance.shutdown.assert_awaited()
    # coordinator-internal: _loop is set by run_forever() itself, no public setter/reader for the raw slot
    assert hassette_instance._loop is asyncio.get_running_loop(), f"Event loop does not match {hassette_instance._loop}"
    assert hassette_instance.loop_thread_id == threading.get_ident(), "Thread ID does not match"


async def test_run_forever_handles_session_init_failure(hassette_instance: Hassette) -> None:
    """run_forever triggers shutdown and raises FatalError when session initialization raises."""
    hassette_instance.database_service.start = Mock()  # pyright: ignore[reportAttributeAccessIssue]
    hassette_instance.wait_for_ready = AsyncMock(return_value=True)
    hassette_instance.shutdown = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    hassette_instance.session_manager.mark_orphaned_sessions = AsyncMock(side_effect=RuntimeError("db broke"))
    hassette_instance.session_manager.create_session = AsyncMock()

    with pytest.raises(FatalError):
        await hassette_instance.run_forever()

    hassette_instance.session_manager.mark_orphaned_sessions.assert_awaited_once()
    hassette_instance.session_manager.create_session.assert_not_awaited()
    hassette_instance.shutdown.assert_awaited()


async def test_run_forever_handles_startup_failure(hassette_instance: Hassette) -> None:
    """run_forever triggers shutdown and raises FatalError when resources fail to become ready."""
    hassette_instance.database_service.start = Mock()  # pyright: ignore[reportAttributeAccessIssue]
    for child in hassette_instance.children:
        if child is not hassette_instance.database_service:
            child.start = Mock()  # pyright: ignore[reportAttributeAccessIssue]
    # DB wait succeeds (True), all-children wait fails (False)
    hassette_instance.wait_for_ready = AsyncMock(side_effect=[True, False])
    hassette_instance.shutdown = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    hassette_instance.session_manager.mark_orphaned_sessions = AsyncMock()
    hassette_instance.session_manager.create_session = AsyncMock()

    with pytest.raises(FatalError):
        await hassette_instance.run_forever()

    assert hassette_instance.wait_for_ready.await_count == 2
    hassette_instance.shutdown.assert_awaited_once()
    assert hassette_instance.ready_event.is_set(), "Ready event was not set"


async def test_run_forever_cleans_up_detectors_when_db_start_fails(hassette_instance: Hassette) -> None:
    """A failure starting the database service tears the watchdog and Tier 2 monkeypatches down.

    database_service.start() runs after the watchdog + Tier 2 guard are installed but before the
    managed startup try. Without cleanup-on-failure, a raise here would skip before_shutdown(),
    leaking the daemon thread and process-global patches. This drives the real shutdown() path and
    asserts both detectors are actually gone afterward — not merely that shutdown() was called.
    """
    # dev_mode=True forces Tier 2 to install, so the teardown assertions below are non-vacuous.
    hassette_instance.config.dev_mode = True
    hassette_instance.config.blocking_io.deep_detection_enabled = True
    hassette_instance.database_service.start = Mock(side_effect=RuntimeError("db start broke"))  # pyright: ignore[reportAttributeAccessIssue]

    real_install = core_module.install_block_io_guard
    try:
        with (
            patch.object(core_module, "install_block_io_guard", wraps=real_install) as install_spy,
            pytest.raises(FatalError),
        ):
            await hassette_instance.run_forever()

        # The guard really installed (so the next assertion can't pass vacuously), and the real
        # shutdown() path (not mocked) tore both detectors back down.
        install_spy.assert_called_once()
        assert not block_io_guard.is_installed(), "Tier 2 guard leaked after startup failure"
        # coordinator-internal: no public accessor for the watchdog slot
        assert hassette_instance._loop_watchdog is None, "Loop watchdog leaked after startup failure"
    finally:
        # Safety net: never let a failed assertion leak process-global patches into other tests.
        block_io_guard.uninstall()


async def test_before_shutdown_removes_listeners_and_finalizes(hassette_instance: Hassette) -> None:
    """before_shutdown removes bus listeners and finalizes the session.

    Logging cleanup (shutdown_logging) is NOT performed here — it is handled
    by LoggingService.on_shutdown() via the Resource lifecycle dependency graph.
    """
    hassette_instance.bus.remove_all_listeners = Mock()
    hassette_instance.session_manager.finalize_session = AsyncMock()

    await hassette_instance.before_shutdown()

    hassette_instance.bus.remove_all_listeners.assert_called_once()
    hassette_instance.session_manager.finalize_session.assert_awaited_once()


async def test_before_shutdown_finalizes_even_when_listener_removal_fails(hassette_instance: Hassette) -> None:
    """before_shutdown still finalizes session when remove_all_listeners raises.

    Logging cleanup (shutdown_logging) is NOT performed here — it is handled
    by LoggingService.on_shutdown() via the Resource lifecycle dependency graph.
    """
    hassette_instance.bus.remove_all_listeners = Mock(side_effect=RuntimeError("bus error"))
    hassette_instance.session_manager.finalize_session = AsyncMock()

    await hassette_instance.before_shutdown()

    hassette_instance.bus.remove_all_listeners.assert_called_once()
    hassette_instance.session_manager.finalize_session.assert_awaited_once()


def test_before_shutdown_contains_no_logging_cleanup() -> None:
    """before_shutdown() must not reference shutdown_logging — cleanup is in LoggingService."""
    # shutdown_logging is removed from logging_.py entirely — verify it's not importable
    assert not hasattr(core_module, "shutdown_logging"), (
        "shutdown_logging was re-added to core.py; logging cleanup must stay in LoggingService"
    )

    # Verify before_shutdown source does not contain shutdown_logging reference
    source = inspect.getsource(Hassette.before_shutdown)
    assert "shutdown_logging" not in source, (
        "before_shutdown() must not call shutdown_logging(); use LoggingService.on_shutdown() instead"
    )


async def test_concurrent_crash_and_finalize_are_serialized(hassette_instance: Hassette) -> None:
    """on_service_crashed and finalize_session on SessionManager coordinate via _session_lock.

    Verifies that concurrent crash recording and session finalization don't
    interleave — the lock forces one to complete before the other starts.
    """
    sm = hassette_instance.session_manager
    sm._session_id = 42  # coordinator-internal
    sm._session_error = False  # coordinator-internal

    call_order: list[str] = []
    crash_holding_lock = asyncio.Event()
    crash_may_release = asyncio.Event()

    async def slow_crash(_event: typing.Any) -> None:
        """Simulate crash handler that holds the lock while doing slow work."""
        async with sm._session_lock:  # coordinator-internal
            call_order.append("crash_acquired")
            crash_holding_lock.set()
            await crash_may_release.wait()  # hold lock until test says release
            call_order.append("crash_released")

    sm._database_service = Mock()  # coordinator-internal
    sm._database_service.db = AsyncMock()  # coordinator-internal

    submit_calls: list[str] = []

    async def tracking_submit(coro: typing.Any) -> None:
        """Track when finalize's submit actually executes, then consume the coroutine."""
        submit_calls.append("submit")
        await coro

    sm._database_service.submit = tracking_submit  # coordinator-internal

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
    hassette_instance.database_service.start()

    hassette_instance.database_service.start.assert_called_once()  # pyright: ignore[reportAttributeAccessIssue]
    for child in hassette_instance.children:
        if child is not hassette_instance.database_service:
            child.start.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]


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

        restart_spec = RestartSpec()
        depends_on: ClassVar[list[type[Resource]]] = [_GhostDep]

    with pytest.raises(ValueError, match="_GhostDep"):
        validate_dependency_graph([_StubService])
