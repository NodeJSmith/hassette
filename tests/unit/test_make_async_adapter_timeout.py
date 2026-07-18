"""Unit tests for make_async_adapter TimeoutError handling."""

import pytest

from hassette.core.sync_executor_service import SyncExecutorService
from hassette.task_bucket.task_bucket import TaskBucket
from hassette.test_utils.mock_hassette import make_mock_hassette


async def test_sync_fn_timeout_error_propagates_cleanly(sync_service: SyncExecutorService) -> None:
    """TimeoutError in sync handler propagates without being caught by the except Exception block."""
    hassette = make_mock_hassette()
    bucket = TaskBucket(hassette)
    bucket._sync_service = sync_service

    def sync_fn() -> None:
        raise TimeoutError("timed out")

    adapted = bucket.make_async_adapter(sync_fn)

    with pytest.raises(TimeoutError):
        await adapted()
