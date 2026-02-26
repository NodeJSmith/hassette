import asyncio
import threading
import typing
from contextlib import suppress
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from hassette import Hassette
from hassette.bus import Bus
from hassette.config.config import HassetteConfig
from hassette.core.api_resource import ApiResource
from hassette.core.app_handler import AppHandler
from hassette.core.bus_service import BusService
from hassette.core.data_sync_service import DataSyncService
from hassette.core.database_service import DatabaseService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.service_watcher import ServiceWatcher
from hassette.core.web_api_service import WebApiService
from hassette.core.websocket_service import WebsocketService
from hassette.scheduler import Scheduler
from hassette.test_utils import wait_for

if typing.TYPE_CHECKING:
    from hassette.events import Event
    from hassette.resources.base import Resource


@pytest.fixture
async def hassette_instance(test_config: HassetteConfig):
    """Provide a fresh Hassette instance and restore context afterwards."""
    test_config.reload()
    instance = Hassette(test_config)
    try:
        yield instance
    finally:
        with suppress(Exception):
            if not instance._send_stream._closed:
                await instance._send_stream.aclose()

        with suppress(Exception):
            if not instance._receive_stream._closed:
                await instance._receive_stream.aclose()

        with suppress(Exception):
            if not instance._bus_service.stream._closed:
                await instance._bus_service.stream.aclose()


def test_unique_name_is_constant(hassette_instance: Hassette) -> None:
    """unique_name always returns the static identifier."""
    assert hassette_instance.unique_name == "Hassette"


def test_constructor_registers_background_services(hassette_instance: Hassette) -> None:
    """Constructor wires up expected services and resources."""
    assert isinstance(hassette_instance._database_service, DatabaseService)
    assert isinstance(hassette_instance._bus_service, BusService)
    assert isinstance(hassette_instance._service_watcher, ServiceWatcher)
    assert isinstance(hassette_instance._websocket_service, WebsocketService)
    assert isinstance(hassette_instance._file_watcher, FileWatcherService)
    assert isinstance(hassette_instance._app_handler, AppHandler)
    assert isinstance(hassette_instance._scheduler_service, SchedulerService)
    assert isinstance(hassette_instance._api_service, ApiResource)
    assert isinstance(hassette_instance._data_sync_service, DataSyncService)
    assert isinstance(hassette_instance._web_api_service, WebApiService)
    assert isinstance(hassette_instance._bus, Bus)
    assert isinstance(hassette_instance._scheduler, Scheduler)
    assert hassette_instance.api is not None

    expected_children = [
        hassette_instance._database_service,
        hassette_instance._bus_service,
        hassette_instance._service_watcher,
        hassette_instance._websocket_service,
        hassette_instance._file_watcher,
        hassette_instance._app_handler,
        hassette_instance._scheduler_service,
        hassette_instance._api_service,
        hassette_instance._data_sync_service,
        hassette_instance._web_api_service,
        hassette_instance._bus,
        hassette_instance._scheduler,
        hassette_instance.api,
    ]
    for child in expected_children:
        assert child in hassette_instance.children


async def test_event_streams_closed_reflects_state(hassette_instance: Hassette) -> None:
    """event_streams_closed mirrors the underlying stream lifecycle."""
    assert hassette_instance.event_streams_closed is False, "Streams should start open"
    await hassette_instance._send_stream.aclose()
    await hassette_instance._receive_stream.aclose()
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

    received_topic, received_event = await hassette_instance._receive_stream.receive()
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
    """run_forever starts resources, waits for readiness, and shuts down when signalled."""
    start_resources = Mock()
    hassette_instance._start_resources = start_resources
    hassette_instance.wait_for_ready = AsyncMock(return_value=True)
    hassette_instance.shutdown = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    hassette_instance._mark_orphaned_sessions = AsyncMock()
    hassette_instance._create_session = AsyncMock()
    bus_subscribe = Mock()
    hassette_instance._bus.on_hassette_service_crashed = bus_subscribe

    task = asyncio.create_task(hassette_instance.run_forever())
    asyncio.get_event_loop().call_later(0.5, hassette_instance.shutdown_event.set)
    await wait_for(lambda: start_resources.called, desc="run_forever started")
    await task

    start_resources.assert_called_once()
    hassette_instance.wait_for_ready.assert_awaited_once_with(
        list(hassette_instance.children), timeout=hassette_instance.config.startup_timeout_seconds
    )
    hassette_instance._mark_orphaned_sessions.assert_awaited_once()
    hassette_instance._create_session.assert_awaited_once()
    bus_subscribe.assert_called_once_with(handler=hassette_instance._on_service_crashed)
    hassette_instance.shutdown.assert_awaited()
    assert hassette_instance._loop is asyncio.get_running_loop(), f"Event loop does not match {hassette_instance._loop}"
    assert hassette_instance._loop_thread_id == threading.get_ident(), "Thread ID does not match"


async def test_run_forever_handles_session_init_failure(hassette_instance: Hassette) -> None:
    """run_forever triggers shutdown when session initialization raises."""
    hassette_instance._start_resources = Mock()
    hassette_instance.wait_for_ready = AsyncMock(return_value=True)
    hassette_instance.shutdown = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    hassette_instance._mark_orphaned_sessions = AsyncMock(side_effect=RuntimeError("db broke"))
    hassette_instance._create_session = AsyncMock()

    await hassette_instance.run_forever()

    hassette_instance._mark_orphaned_sessions.assert_awaited_once()
    hassette_instance._create_session.assert_not_awaited()
    hassette_instance.shutdown.assert_awaited()


async def test_run_forever_handles_startup_failure(hassette_instance: Hassette) -> None:
    """run_forever triggers shutdown when resources fail to become ready."""
    hassette_instance._start_resources = Mock()
    hassette_instance.wait_for_ready = AsyncMock(return_value=False)
    hassette_instance.shutdown = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

    await hassette_instance.run_forever()

    hassette_instance.wait_for_ready.assert_awaited_once()
    hassette_instance.shutdown.assert_awaited_once()
    assert hassette_instance.ready_event.is_set(), "Ready event was not set"


async def test_before_shutdown_removes_listeners_and_finalizes(hassette_instance: Hassette) -> None:
    """before_shutdown removes bus listeners and finalizes the session."""
    completed_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    completed_future.set_result(None)
    hassette_instance._bus.remove_all_listeners = Mock(return_value=completed_future)
    hassette_instance._finalize_session = AsyncMock()

    await hassette_instance.before_shutdown()

    hassette_instance._bus.remove_all_listeners.assert_called_once()
    hassette_instance._finalize_session.assert_awaited_once()


async def test_before_shutdown_finalizes_even_when_listener_removal_fails(hassette_instance: Hassette) -> None:
    """before_shutdown still finalizes session when remove_all_listeners raises."""
    hassette_instance._bus.remove_all_listeners = AsyncMock(side_effect=RuntimeError("bus error"))
    hassette_instance._finalize_session = AsyncMock()

    await hassette_instance.before_shutdown()

    hassette_instance._bus.remove_all_listeners.assert_awaited_once()
    hassette_instance._finalize_session.assert_awaited_once()
