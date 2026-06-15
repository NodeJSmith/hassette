"""Unit tests for ServiceWatcher.handle_exhaustion and cooldown_and_retry (WP02).

Verifies:
- handle_exhaustion sets EXHAUSTED_COOLING on the service instance for TRANSIENT services
- handle_exhaustion sets EXHAUSTED_DEAD on the service instance for TEMPORARY services
- cooldown_and_retry transitions EXHAUSTED_COOLING → EXHAUSTED_DEAD when cooldown cycle limit exceeded
- Status assignment is skipped (with warning) when get_service returns empty list
"""

import asyncio
import logging
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from hassette.core.service_watcher import ServiceWatcher
from hassette.events.hassette import ServiceStatusPayload
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.test_utils import make_mock_hassette
from hassette.types import ResourceStatus
from hassette.types.enums import ResourceRole, RestartType


def build_hassette(*, strict_lifecycle: bool = False) -> AsyncMock:
    """Minimal Hassette stub for ServiceWatcher unit tests."""
    hassette = make_mock_hassette(
        sealed=False,
        strict_lifecycle=strict_lifecycle,
        lifecycle={"resource_shutdown_timeout_seconds": 1, "task_cancellation_timeout_seconds": 1},
    )
    hassette.send_event = AsyncMock()
    hassette.shutdown = AsyncMock()
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


def make_failed_payload(service: Service) -> ServiceStatusPayload:
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


def make_watcher(hassette: MagicMock) -> ServiceWatcher:
    """Build a ServiceWatcher that skips its Bus child (not needed for unit tests)."""
    watcher = ServiceWatcher.__new__(ServiceWatcher)
    # Initialize LifecycleMixin state
    watcher.ready_event = asyncio.Event()
    watcher.shutdown_event = asyncio.Event()
    watcher._ready_reason = None
    watcher._status = ResourceStatus.NOT_STARTED
    watcher._previous_status = ResourceStatus.NOT_STARTED
    watcher.shutdown_completed = False
    watcher.shutting_down = False
    watcher.initializing = False
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
    task_bucket.spawn = Mock(side_effect=lambda coro, **_kw: asyncio.create_task(coro))
    watcher.task_bucket = task_bucket
    return watcher


async def test_exhausted_cooling_sets_status_on_instance():
    """TRANSIENT service: handle_exhaustion sets EXHAUSTED_COOLING on the service instance."""
    hassette = build_hassette()
    service = _DummyService(hassette)
    service._status = ResourceStatus.FAILED
    hassette.children = [service]

    watcher = make_watcher(hassette)
    spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=9999)
    payload = make_failed_payload(service)

    spawned_coros: list = []

    def _capture_spawn(coro, **_kw):
        spawned_coros.append(coro)
        task = MagicMock()
        task.done.return_value = False
        return task

    # Patch task_bucket.spawn to capture (and close) the coroutine without running it
    with patch.object(watcher.task_bucket, "spawn", side_effect=_capture_spawn):
        await watcher.handle_exhaustion(
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


async def test_exhausted_dead_sets_status_on_instance():
    """TEMPORARY service: handle_exhaustion sets EXHAUSTED_DEAD on the service instance."""
    hassette = build_hassette()
    service = _TempService(hassette)
    service._status = ResourceStatus.FAILED
    hassette.children = [service]

    watcher = make_watcher(hassette)
    spec = RestartSpec(restart_type=RestartType.TEMPORARY)
    payload = make_failed_payload(service)

    await watcher.handle_exhaustion(
        name=service.class_name,
        role=service.role,
        key=f"{service.class_name}:{service.role}",
        spec=spec,
        original_data=payload,
    )

    assert service.status == ResourceStatus.EXHAUSTED_DEAD, (
        f"Expected EXHAUSTED_DEAD on service instance, got {service.status}"
    )


async def test_cooldown_exceeded_sets_exhausted_dead():
    """cooldown_and_retry transitions EXHAUSTED_COOLING → EXHAUSTED_DEAD when max_cooldown_cycles exceeded."""
    hassette = build_hassette()
    service = _DummyService(hassette)
    service._status = ResourceStatus.EXHAUSTED_COOLING
    hassette.children = [service]

    watcher = make_watcher(hassette)
    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        cooldown_seconds=0.001,
        max_cooldown_cycles=1,
    )
    key = f"{service.class_name}:{service.role}"
    # Pre-set cycle count to exceed max_cooldown_cycles on next call
    watcher._cooldown_cycles[key] = 1  # will become 2 > max_cooldown_cycles=1

    await watcher.cooldown_and_retry(
        name=service.class_name,
        role=service.role,
        key=key,
        spec=spec,
    )

    assert service.status == ResourceStatus.EXHAUSTED_DEAD, (
        f"Expected EXHAUSTED_DEAD after cooldown exceeded, got {service.status}"
    )


async def test_exhausted_status_skipped_when_service_not_found():
    """When get_service returns empty list, status set is skipped — no exception, event still emitted."""
    hassette = build_hassette()
    hassette.children = []

    watcher = make_watcher(hassette)
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

    await watcher.handle_exhaustion(
        name="NonExistentService",
        role=ResourceRole.SERVICE,
        key="NonExistentService:service",
        spec=spec,
        original_data=payload,
    )

    hassette.send_event.assert_called()
