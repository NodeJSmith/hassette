"""Tests for ``cleanup(timeout=0)`` on ``Resource`` and ``App``.

Verifies:
- An explicit ``timeout=0`` reaches ``asyncio.wait_for`` unchanged instead of being replaced
  by the configured shutdown-timeout default (the old ``timeout or config_default`` form
  treated ``0`` as "unset").
- ``timeout=None`` still falls back to the configured default.
"""

import asyncio
import logging
from contextlib import suppress
from unittest.mock import AsyncMock, patch

import pytest

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.resources.base import Resource
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ConcreteResource


async def _pending_init_task(resource: Resource) -> None:
    """Attach a never-finishing ``_init_task`` so ``cleanup()`` reaches its ``wait_for``."""
    started = asyncio.Event()

    async def never_finishes() -> None:
        started.set()
        await asyncio.Event().wait()

    resource._init_task = asyncio.ensure_future(never_finishes())
    await asyncio.wait_for(started.wait(), timeout=1)


async def _record_cleanup_timeouts(resource: Resource, timeout: float | None) -> list[float | None]:
    """Call ``resource.cleanup(timeout=timeout)`` and return the timeouts it passed to ``wait_for``."""
    seen: list[float | None] = []
    real_wait_for = asyncio.wait_for

    async def recording_wait_for(aw, timeout=None):
        seen.append(timeout)
        return await real_wait_for(aw, timeout=timeout)

    # timeout=0 legitimately expires against a still-pending init task; the timeout value
    # recorded above is what this test asserts on, not the outcome of the wait.
    with patch.object(asyncio, "wait_for", recording_wait_for), suppress(TimeoutError, asyncio.CancelledError):
        await resource.cleanup(timeout=timeout)

    return seen


class TestResourceCleanupTimeout:
    @pytest.mark.parametrize(("passed", "expected"), [(0, 0), (None, 30)])
    async def test_timeout_reaches_wait_for(self, passed: float | None, expected: float) -> None:
        hassette = make_mock_hassette(sealed=False)
        hassette.config.lifecycle.resource_shutdown_timeout_seconds = 30
        resource = ConcreteResource(hassette=hassette)
        await _pending_init_task(resource)

        assert await _record_cleanup_timeouts(resource, passed) == [expected]


class TestAppCleanupTimeout:
    @pytest.mark.parametrize(("passed", "expected"), [(0, 0), (None, 45)])
    async def test_timeout_reaches_wait_for(self, passed: float | None, expected: float) -> None:
        """``App.cleanup()`` resolves its own default, then runs the real inherited cleanup."""
        hassette = make_mock_hassette(sealed=False)
        hassette.config.lifecycle.app_shutdown_timeout_seconds = 45
        hassette.config.lifecycle.resource_shutdown_timeout_seconds = 30

        # App's real __init__ needs a full manifest/config wiring that none of this exercises;
        # the inherited cleanup path only reads the attributes set below.
        app = object.__new__(App)
        app.hassette = hassette
        app.app_config = AppConfig(instance_name="TestApp.0")
        app.logger = logging.getLogger("TestApp.0")
        app._pending_start_task = None
        app.cache = AsyncMock()  # filesystem-backed cache — a genuine boundary
        await _pending_init_task(app)

        # Only the timeout resolution is asserted here: with timeout=0 the inherited wait
        # legitimately expires, so App.cleanup() never reaches its own cache.close().
        assert await _record_cleanup_timeouts(app, passed) == [expected]
