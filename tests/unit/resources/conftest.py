"""Shared fixtures for unit/resources tests."""

import asyncio
import threading
from unittest.mock import AsyncMock, Mock


def _make_hassette_stub(*, strict_lifecycle: bool = False) -> AsyncMock:
    """Minimal stub that satisfies Resource.__init__ and TaskBucket.spawn."""
    hassette = AsyncMock()
    hassette.config.log_level = "DEBUG"
    hassette.config.strict_lifecycle = strict_lifecycle
    hassette.config.data_dir = "/tmp/hassette-test"
    hassette.config.default_cache_size = 1024
    hassette.config.resource_shutdown_timeout_seconds = 1
    hassette.config.startup_timeout_seconds = 30
    hassette.config.task_cancellation_timeout_seconds = 1
    hassette.config.task_bucket_log_level = "DEBUG"
    hassette.config.dev_mode = False
    hassette.event_streams_closed = False
    hassette.ready_event = asyncio.Event()
    hassette.ready_event.set()
    hassette.shutdown_event = asyncio.Event()
    hassette._loop_thread_id = threading.get_ident()
    hassette.loop = asyncio.get_running_loop()
    # register_removal_callback and deregister_removal_callback must be sync
    # callables so Scheduler.__init__/on_shutdown can call them directly without
    # creating an unawaited coroutine.
    hassette._scheduler_service.register_removal_callback = Mock()
    hassette._scheduler_service.deregister_removal_callback = Mock()
    hassette._bus_service.remove_listeners_by_owner = Mock()
    hassette._bus_service.get_listeners_by_owner = Mock(return_value=[])
    return hassette
