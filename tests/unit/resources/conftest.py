"""Shared fixtures for unit/resources tests."""

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def hassette_stub() -> AsyncMock:
    """Minimal stub that satisfies Resource.__init__ and TaskBucket.spawn."""
    stub = _make_hassette_stub()
    return stub


def _make_hassette_stub() -> AsyncMock:
    """Minimal stub that satisfies Resource.__init__ and TaskBucket.spawn.

    Available as both a fixture (hassette_stub) and a plain function
    for tests that need to call it multiple times or inline.
    """
    hassette = AsyncMock()
    hassette.config.log_level = "DEBUG"
    hassette.config.data_dir = "/tmp/hassette-test"
    hassette.config.default_cache_size = 1024
    hassette.config.resource_shutdown_timeout_seconds = 1
    hassette.config.task_cancellation_timeout_seconds = 1
    hassette.config.task_bucket_log_level = "DEBUG"
    hassette.config.dev_mode = False
    hassette.event_streams_closed = False
    hassette.ready_event = asyncio.Event()
    hassette.ready_event.set()
    hassette._loop_thread_id = threading.get_ident()
    hassette.loop = asyncio.get_running_loop()
    return hassette
