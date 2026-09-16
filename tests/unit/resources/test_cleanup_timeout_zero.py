"""Tests for ``cleanup(timeout=0)`` on ``Resource`` and ``App``.

Verifies:
- An explicit ``timeout=0`` reaches ``asyncio.wait_for`` unchanged instead of being replaced
  by the configured shutdown-timeout default (the old ``timeout or config_default`` form
  treated ``0`` as "unset").
- ``timeout=None`` still falls back to the configured default.
"""

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, patch

import pytest

from hassette.app.app import App
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ConcreteResource


async def _pending_init_task(resource: ConcreteResource) -> None:
    """Attach a never-finishing ``_init_task`` so ``cleanup()`` reaches its ``wait_for``."""
    started = asyncio.Event()

    async def never_finishes() -> None:
        started.set()
        await asyncio.Event().wait()

    resource._init_task = asyncio.ensure_future(never_finishes())
    await asyncio.wait_for(started.wait(), timeout=1)


async def _record_cleanup_timeouts(resource: ConcreteResource, timeout: float | None) -> list[float | None]:
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
    async def test_zero_timeout_is_not_replaced_by_config_default(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        hassette.config.lifecycle.resource_shutdown_timeout_seconds = 30
        resource = ConcreteResource(hassette=hassette)
        await _pending_init_task(resource)

        assert await _record_cleanup_timeouts(resource, 0) == [0]

    async def test_none_timeout_falls_back_to_config_default(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        hassette.config.lifecycle.resource_shutdown_timeout_seconds = 30
        resource = ConcreteResource(hassette=hassette)
        await _pending_init_task(resource)

        assert await _record_cleanup_timeouts(resource, None) == [30]


class TestAppCleanupTimeout:
    @pytest.mark.parametrize(("passed", "expected"), [(0, 0), (None, 45)])
    async def test_timeout_forwarded_to_resource_cleanup(self, passed: float | None, expected: float) -> None:
        """``App.cleanup()`` forwards an explicit ``0`` rather than substituting the default."""
        hassette = make_mock_hassette(sealed=False)
        hassette.config.lifecycle.app_shutdown_timeout_seconds = 45
        app = object.__new__(App)
        app.hassette = hassette
        app.cache = AsyncMock()

        with patch("hassette.resources.base.Resource.cleanup", new=AsyncMock()) as base_cleanup:
            await App.cleanup(app, timeout=passed)

        base_cleanup.assert_awaited_once_with(timeout=expected)
