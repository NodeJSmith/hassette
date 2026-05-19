"""Unit tests for ServiceWatcher._handle_exhaustion and _cooldown_and_retry (WP02).

Verifies:
- _handle_exhaustion sets EXHAUSTED_COOLING on the service instance for TRANSIENT services
- _handle_exhaustion sets EXHAUSTED_DEAD on the service instance for TEMPORARY services
- _cooldown_and_retry transitions EXHAUSTED_COOLING → EXHAUSTED_DEAD when cooldown cycle limit exceeded
- Status assignment is skipped (with warning) when _get_service returns empty list
"""

import asyncio
import logging
import threading
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.core.service_watcher import ServiceWatcher
from hassette.events.hassette import ServiceStatusPayload
from hassette.resources.base import RestartSpec, Service
from hassette.types import ResourceStatus
from hassette.types.enums import ResourceRole, RestartType

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_hassette_stub(*, strict_lifecycle: bool = False) -> MagicMock:
    """Minimal Hassette stub for ServiceWatcher unit tests."""
    hassette = MagicMock()
    hassette.config.logging.log_level = "DEBUG"
    hassette.config.strict_lifecycle = strict_lifecycle
    hassette.config.data_dir = "/tmp/hassette-test"
    hassette.config.default_cache_size = 1024
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 1
    hassette.config.lifecycle.startup_timeout_seconds = 30
    hassette.config.lifecycle.task_cancellation_timeout_seconds = 1
    hassette.config.logging.task_bucket = "DEBUG"
    hassette.config.dev_mode = False
    hassette.config.logging.service_watcher = "DEBUG"
    hassette.event_streams_closed = False
    hassette.ready_event = asyncio.Event()
    hassette.ready_event.set()
    hassette.shutdown_event = asyncio.Event()
    hassette._loop_thread_id = threading.get_ident()
    hassette.children = []
    hassette.send_event = AsyncMock()
    hassette.shutdown = AsyncMock()
    # Sync mock methods
    hassette._scheduler_service.register_removal_callback = Mock()
    hassette._scheduler_service.deregister_removal_callback = Mock()
    return hassette


class _DummyService(Service):
    """Minimal concrete Service for exhaustion tests."""

    restart_spec: ClassVar[RestartSpec] = RestartSpec(restart_type=RestartType.TRANSIENT)

    async def serve(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise


class _TempService(Service):
    """TEMPORARY restart type service for EXHAUSTED_DEAD tests."""

    restart_spec: ClassVar[RestartSpec] = RestartSpec(restart_type=RestartType.TEMPORARY)

    async def serve(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise


def _make_failed_payload(service: Service) -> ServiceStatusPayload:
    """Build a minimal FAILED ServiceStatusPayload."""
    return ServiceStatusPayload(
        resource_name=service.class_name,
        role=service.role,
        status=ResourceStatus.FAILED,
        previous_status=ResourceStatus.RUNNING,
        exception="test error",
        exception_type="RuntimeError",
        exception_traceback=None,
        ready=False,
        ready_phase=None,
    )


def _make_watcher(hassette: MagicMock) -> ServiceWatcher:
    """Build a ServiceWatcher that skips its Bus child (not needed for unit tests)."""
    watcher = ServiceWatcher.__new__(ServiceWatcher)
    # Initialize LifecycleMixin state
    watcher.ready_event = asyncio.Event()
    watcher.shutdown_event = asyncio.Event()
    watcher._ready_reason = None
    watcher._status = ResourceStatus.NOT_STARTED
    watcher._previous_status = ResourceStatus.NOT_STARTED
    watcher._shutdown_completed = False
    watcher._shutting_down = False
    watcher._initializing = False
    watcher._init_task = None
    watcher._cache = None
    watcher.hassette = hassette
    watcher.parent = hassette
    watcher.children = []
    watcher._budgets = {}
    watcher._restarting = set()
    watcher._cooldown_tasks = {}
    watcher._cooldown_cycles = {}
    watcher.logger = logging.getLogger("hassette.test.service_watcher")
    # Task bucket mock
    task_bucket = MagicMock()
    task_bucket.spawn = Mock(side_effect=lambda coro, **_kw: asyncio.ensure_future(coro))
    watcher.task_bucket = task_bucket
    return watcher


# ---------------------------------------------------------------------------
# Tests: _handle_exhaustion sets status on service instance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exhausted_cooling_sets_status_on_instance():
    """TRANSIENT service: _handle_exhaustion sets EXHAUSTED_COOLING on the service instance."""
    hassette = _make_hassette_stub()
    service = _DummyService(hassette)
    service._status = ResourceStatus.FAILED
    hassette.children = [service]

    watcher = _make_watcher(hassette)
    spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=9999)
    payload = _make_failed_payload(service)

    spawned_coros: list = []

    def _capture_spawn(coro, **_kw):
        spawned_coros.append(coro)
        task = MagicMock()
        task.done.return_value = False
        return task

    # Patch task_bucket.spawn to capture (and close) the coroutine without running it
    with patch.object(watcher.task_bucket, "spawn", side_effect=_capture_spawn):
        await watcher._handle_exhaustion(
            name=service.class_name,
            role=service.role,
            key=f"{service.class_name}:{service.role}",
            spec=spec,
            original_data=payload,
        )

    # Close captured coroutines to avoid "coroutine was never awaited" warnings
    for coro in spawned_coros:
        coro.close()

    assert service.status == ResourceStatus.EXHAUSTED_COOLING, (
        f"Expected EXHAUSTED_COOLING on service instance, got {service.status}"
    )


@pytest.mark.asyncio
async def test_exhausted_dead_sets_status_on_instance():
    """TEMPORARY service: _handle_exhaustion sets EXHAUSTED_DEAD on the service instance."""
    hassette = _make_hassette_stub()
    service = _TempService(hassette)
    service._status = ResourceStatus.FAILED
    hassette.children = [service]

    watcher = _make_watcher(hassette)
    spec = RestartSpec(restart_type=RestartType.TEMPORARY)
    payload = _make_failed_payload(service)

    await watcher._handle_exhaustion(
        name=service.class_name,
        role=service.role,
        key=f"{service.class_name}:{service.role}",
        spec=spec,
        original_data=payload,
    )

    assert service.status == ResourceStatus.EXHAUSTED_DEAD, (
        f"Expected EXHAUSTED_DEAD on service instance, got {service.status}"
    )


@pytest.mark.asyncio
async def test_cooldown_exceeded_sets_exhausted_dead():
    """_cooldown_and_retry transitions EXHAUSTED_COOLING → EXHAUSTED_DEAD when max_cooldown_cycles exceeded."""
    hassette = _make_hassette_stub()
    service = _DummyService(hassette)
    service._status = ResourceStatus.EXHAUSTED_COOLING
    hassette.children = [service]

    watcher = _make_watcher(hassette)
    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        cooldown_seconds=0.001,
        max_cooldown_cycles=1,
    )
    key = f"{service.class_name}:{service.role}"
    # Pre-set cycle count to exceed max_cooldown_cycles on next call
    watcher._cooldown_cycles[key] = 1  # will become 2 > max_cooldown_cycles=1

    await watcher._cooldown_and_retry(
        name=service.class_name,
        role=service.role,
        key=key,
        spec=spec,
    )

    assert service.status == ResourceStatus.EXHAUSTED_DEAD, (
        f"Expected EXHAUSTED_DEAD after cooldown exceeded, got {service.status}"
    )


@pytest.mark.asyncio
async def test_exhausted_status_skipped_when_service_not_found():
    """When _get_service returns empty list, status set is skipped — no exception, event still emitted."""
    hassette = _make_hassette_stub()
    hassette.children = []

    watcher = _make_watcher(hassette)
    spec = RestartSpec(restart_type=RestartType.TEMPORARY)

    payload = ServiceStatusPayload(
        resource_name="NonExistentService",
        role=ResourceRole.SERVICE,
        status=ResourceStatus.FAILED,
        previous_status=ResourceStatus.RUNNING,
        exception="test",
        exception_type="RuntimeError",
        exception_traceback=None,
        ready=False,
        ready_phase=None,
    )

    await watcher._handle_exhaustion(
        name="NonExistentService",
        role=ResourceRole.SERVICE,
        key="NonExistentService:service",
        spec=spec,
        original_data=payload,
    )

    hassette.send_event.assert_called()
