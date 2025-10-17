import asyncio
import threading
import typing
from contextlib import suppress
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.config.core_config import HassetteConfig
from hassette.core import context
from hassette.core.core import Hassette
from hassette.core.resources.bus.bus import Bus
from hassette.core.resources.scheduler.scheduler import Scheduler
from hassette.core.services.api_service import _ApiService
from hassette.core.services.app_handler import _AppHandler
from hassette.core.services.bus_service import _BusService
from hassette.core.services.file_watcher import _FileWatcher
from hassette.core.services.health_service import _HealthService
from hassette.core.services.scheduler_service import _SchedulerService
from hassette.core.services.service_watcher import _ServiceWatcher
from hassette.core.services.websocket_service import _WebsocketService

if typing.TYPE_CHECKING:
    from hassette.core.resources.base import Resource
    from hassette.events import Event


@pytest.fixture
async def hassette_instance(test_config: HassetteConfig):
    """Provide a fresh Hassette instance and restore context afterwards."""
    previous_instance = context.HASSETTE_INSTANCE.get(None)
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

        context.HASSETTE_INSTANCE.set(previous_instance)


async def test_run_sync_raises_inside_loop(hassette_with_bus: Hassette) -> None:
    """run_sync rejects being invoked inside the running event loop."""

    async def sample_coroutine():
        return 42

    with pytest.raises(RuntimeError):
        hassette_with_bus.task_bucket.run_sync(sample_coroutine())


def test_unique_name_is_constant(hassette_instance: Hassette) -> None:
    """unique_name always returns the static identifier."""
    assert hassette_instance.unique_name == "Hassette"


def test_constructor_registers_background_services(hassette_instance: Hassette) -> None:
    """Constructor wires up expected services and resources."""
    assert isinstance(hassette_instance._bus_service, _BusService)
    assert isinstance(hassette_instance._service_watcher, _ServiceWatcher)
    assert isinstance(hassette_instance._websocket, _WebsocketService)
    assert isinstance(hassette_instance._health_service, _HealthService)
    assert isinstance(hassette_instance._file_watcher, _FileWatcher)
    assert isinstance(hassette_instance._app_handler, _AppHandler)
    assert isinstance(hassette_instance._scheduler_service, _SchedulerService)
    assert isinstance(hassette_instance._api_service, _ApiService)
    assert isinstance(hassette_instance._bus, Bus)
    assert isinstance(hassette_instance._scheduler, Scheduler)
    assert hassette_instance.api is not None

    expected_children = [
        hassette_instance._bus_service,
        hassette_instance._service_watcher,
        hassette_instance._websocket,
        hassette_instance._health_service,
        hassette_instance._file_watcher,
        hassette_instance._app_handler,
        hassette_instance._scheduler_service,
        hassette_instance._api_service,
        hassette_instance._bus,
        hassette_instance._scheduler,
        hassette_instance.api,
    ]
    for child in expected_children:
        assert child in hassette_instance.children


async def test_event_streams_closed_reflects_state(hassette_instance: Hassette) -> None:
    """event_streams_closed mirrors the underlying stream lifecycle."""
    assert hassette_instance.event_streams_closed is False
    await hassette_instance._send_stream.aclose()
    await hassette_instance._receive_stream.aclose()
    await asyncio.sleep(0)  # allow state to propagate
    assert hassette_instance.event_streams_closed is True


def test_loop_property_raises_when_not_started(hassette_instance: Hassette) -> None:
    """loop property raises when Hassette is not running."""
    with pytest.raises(RuntimeError):
        _ = hassette_instance.loop


async def test_loop_property_returns_running_loop(hassette_instance: Hassette) -> None:
    """loop property returns the configured loop once set."""
    running_loop = asyncio.get_running_loop()
    hassette_instance._loop = running_loop
    assert hassette_instance.loop is running_loop


def test_get_instance_returns_current(hassette_instance: Hassette) -> None:
    """get_instance returns the context-bound Hassette."""
    with context.use(context.HASSETTE_INSTANCE, hassette_instance):
        assert Hassette.get_instance() is hassette_instance


def test_get_instance_raises_when_unset() -> None:
    """get_instance raises when no instance is registered."""
    with context.use(context.HASSETTE_INSTANCE, None), pytest.raises(RuntimeError):
        Hassette.get_instance()


def test_apps_property_forwards_to_handler(hassette_instance: Hassette) -> None:
    """apps property proxies to the app handler."""
    hassette_instance._app_handler = SimpleNamespace(apps={"demo": []})  # type: ignore[assignment]
    assert hassette_instance.apps == {"demo": []}


def test_get_app_forwards_to_handler(hassette_instance: Hassette) -> None:
    """get_app delegates to the handler's get method."""
    handler = SimpleNamespace()
    handler.get = Mock(return_value="app-instance")  # type: ignore[attr-defined]
    hassette_instance._app_handler = handler  # type: ignore[assignment]

    retrieved = hassette_instance.get_app("demo", index=2)

    handler.get.assert_called_once_with("demo", 2)  # type: ignore[attr-defined]
    assert retrieved == "app-instance"


async def test_send_event_writes_to_stream(hassette_instance: Hassette) -> None:
    """send_event pushes topic and payload onto the internal stream."""
    payload = SimpleNamespace(value=123)
    await hassette_instance.send_event("topic.demo", cast("Event", payload))

    received_topic, received_event = await hassette_instance._receive_stream.receive()
    assert received_topic == "topic.demo"
    assert received_event is payload


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
    hassette_instance._start_resources = start_resources  # type: ignore[assignment]
    hassette_instance.wait_for_ready = AsyncMock(return_value=True)  # type: ignore[assignment]
    hassette_instance.shutdown = AsyncMock()  # type: ignore[assignment]

    task = asyncio.create_task(hassette_instance.run_forever())
    asyncio.get_event_loop().call_later(0.5, hassette_instance.shutdown_event.set)
    await asyncio.sleep(0.1)
    await task

    start_resources.assert_called_once()
    hassette_instance.wait_for_ready.assert_awaited_once_with(
        list(hassette_instance.children), timeout=hassette_instance.config.startup_timeout_seconds
    )
    hassette_instance.shutdown.assert_awaited()
    assert hassette_instance._loop is asyncio.get_running_loop(), f"Event loop does not match {hassette_instance._loop}"
    assert hassette_instance._loop_thread_id == threading.get_ident(), "Thread ID does not match"


async def test_run_forever_handles_startup_failure(hassette_instance: Hassette) -> None:
    """run_forever triggers shutdown when resources fail to become ready."""
    hassette_instance._start_resources = Mock()  # type: ignore[assignment]
    hassette_instance.wait_for_ready = AsyncMock(return_value=False)  # type: ignore[assignment]
    hassette_instance.shutdown = AsyncMock()  # type: ignore[assignment]

    await hassette_instance.run_forever()

    hassette_instance.wait_for_ready.assert_awaited_once()
    hassette_instance.shutdown.assert_awaited_once()
    assert hassette_instance.ready_event.is_set(), "Ready event was not set"
