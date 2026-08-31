"""ServiceWatcher mock factories for tests/unit/core/."""

import asyncio
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, Mock

from hassette.core.service_watcher import ServiceWatcher
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.test_utils.helpers import block_until_cancelled
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.types.enums import ResourceStatus, RestartType


class DummyService(Service):
    """Minimal concrete Service for watcher-level tests."""

    restart_spec: RestartSpec = RestartSpec(restart_type=RestartType.TRANSIENT)

    serve = block_until_cancelled  # bound as instance method via the descriptor protocol


class TempService(Service):
    """TEMPORARY restart type service for EXHAUSTED_DEAD tests."""

    restart_spec: RestartSpec = RestartSpec(restart_type=RestartType.TEMPORARY)

    serve = block_until_cancelled  # bound as instance method via the descriptor protocol


def make_watcher_hassette(*, strict_lifecycle: bool = False) -> AsyncMock:
    """Minimal Hassette stub for ServiceWatcher unit tests."""
    hassette = make_mock_hassette(
        sealed=False,
        strict_lifecycle=strict_lifecycle,
        lifecycle={"resource_shutdown_timeout_seconds": 1, "task_cancellation_timeout_seconds": 1},
    )
    hassette.send_event = AsyncMock()
    hassette.shutdown = AsyncMock()
    return hassette


def make_watcher(hassette: MagicMock) -> ServiceWatcher:
    """Build a ServiceWatcher bypassing __init__ (no real Bus child needed)."""
    watcher = ServiceWatcher.__new__(ServiceWatcher)
    watcher.unique_id = uuid.uuid4().hex[:8]
    watcher.ready_event = asyncio.Event()
    watcher.shutdown_event = asyncio.Event()
    watcher._ready_reason = None
    watcher._status = ResourceStatus.NOT_STARTED
    watcher._previous_status = ResourceStatus.NOT_STARTED
    watcher.shutdown_completed = False
    watcher.shutting_down = False
    watcher.initializing = False
    watcher._init_task = None
    watcher.hassette = hassette
    watcher.parent = hassette
    watcher.children = []
    watcher._budgets = {}
    watcher._restarting = set()
    watcher._cooldown_tasks = {}
    watcher._cooldown_cycles = {}
    watcher.logger = logging.getLogger("hassette.test.service_watcher")
    task_bucket = MagicMock()
    task_bucket.spawn = Mock(side_effect=lambda coro, **_kw: asyncio.create_task(coro))
    watcher.task_bucket = task_bucket
    watcher.bus = MagicMock()
    watcher.bus.on = AsyncMock()
    return watcher
