"""BusService/SchedulerService factories for tests/unit/core/."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from hassette.bus.duration_hold import DurationHoldManager
from hassette.bus.router import Router
from hassette.core.bus_service import BusService, compute_elapsed, make_synthetic_state_event
from hassette.core.event_filter import EventFilter
from hassette.core.scheduler_service import SchedulerService
from hassette.test_utils.config import TEST_CONFIG_TIMEOUT_SECONDS


def make_bus_service(
    *, config_timeout: float | None = TEST_CONFIG_TIMEOUT_SECONDS, max_concurrent_dispatches: int = 50
) -> BusService:
    """Create a BusService with mocked internals, bypassing Resource.__init__."""
    svc = BusService.__new__(BusService)
    svc.hassette = MagicMock()
    svc.hassette.config.lifecycle.event_handler_timeout_seconds = config_timeout
    svc.hassette.config.lifecycle.max_concurrent_dispatches = max_concurrent_dispatches
    svc.hassette.config.bus_excluded_domains = ()
    svc.hassette.config.bus_excluded_entities = ()
    svc.hassette.config.logging.all_events = False
    svc._executor = MagicMock()
    svc._executor.execute = AsyncMock()
    svc._executor.register_listener = AsyncMock(return_value=0)
    svc.logger = MagicMock()
    svc._config_resolver = lambda: config_timeout
    svc._event_filter = EventFilter(
        excluded_domains=(),
        excluded_entities=(),
        logger=svc.logger,
    )
    svc.router = Router()
    task_bucket = MagicMock()
    task_bucket.spawn = MagicMock(side_effect=lambda coro, **_kw: asyncio.create_task(coro))
    svc.task_bucket = task_bucket
    svc._duration_hold = DurationHoldManager(
        executor=svc._executor,
        config_resolver=svc._config_resolver,
        state_reader=lambda _entity_id: None,
        remove_listener=lambda _listener: None,
        router=svc.router,
        task_bucket=task_bucket,
        logger=svc.logger,
        make_synthetic_event=make_synthetic_state_event,
        compute_elapsed=compute_elapsed,
    )
    svc._dispatch_pending = 0
    svc._dispatch_idle_event = asyncio.Event()
    svc._dispatch_idle_event.set()
    svc._dispatch_semaphore = asyncio.Semaphore(max_concurrent_dispatches)
    svc._last_saturation_warn_ts = 0.0
    return svc


def make_scheduler_service(
    *,
    config_timeout: float | None = TEST_CONFIG_TIMEOUT_SECONDS,
    behind_schedule_threshold: float = 60,
) -> SchedulerService:
    """Create a SchedulerService with mocked internals, bypassing Resource.__init__."""
    svc = SchedulerService.__new__(SchedulerService)
    svc.hassette = MagicMock()
    svc.hassette.config.scheduler.behind_schedule_threshold_seconds = behind_schedule_threshold
    svc.hassette.config.scheduler.job_timeout_seconds = config_timeout
    svc._removal_callbacks = {}
    svc._jobs_by_id = {}
    svc.logger = MagicMock()
    svc._wakeup_event = asyncio.Event()

    svc._job_queue = MagicMock()
    svc._job_queue.add = AsyncMock(return_value=None)
    svc._job_queue.remove_job = AsyncMock(return_value=True)

    svc._executor = MagicMock()
    svc._executor.execute = AsyncMock()
    svc._executor.mark_job_status = AsyncMock()

    svc.task_bucket = MagicMock()
    svc.task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)

    # Close coroutines immediately to avoid "coroutine was never awaited" warnings
    def _spawn(coro, **_kwargs):
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    svc.task_bucket.spawn = _spawn

    return svc
