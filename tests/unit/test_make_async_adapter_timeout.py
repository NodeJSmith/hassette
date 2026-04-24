"""Unit tests for make_async_adapter TimeoutError handling."""

import asyncio
from unittest.mock import MagicMock

import pytest

from hassette.task_bucket.task_bucket import TaskBucket


async def test_sync_fn_timeout_error_propagates_cleanly() -> None:
    """TimeoutError in sync handler propagates without being caught by the except Exception block."""
    hassette = MagicMock()
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.log_level = "INFO"
    hassette.loop = asyncio.get_running_loop()
    hassette._loop_thread_id = None
    bucket = TaskBucket(hassette, parent=hassette)

    def sync_fn() -> None:
        raise TimeoutError("timed out")

    adapted = bucket.make_async_adapter(sync_fn)

    with pytest.raises(TimeoutError):
        await adapted()
