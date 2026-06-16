"""Unit tests for make_async_adapter TimeoutError handling."""

import pytest

from hassette.task_bucket.task_bucket import TaskBucket
from hassette.test_utils.mock_hassette import make_mock_hassette


async def test_sync_fn_timeout_error_propagates_cleanly() -> None:
    """TimeoutError in sync handler propagates without being caught by the except Exception block."""
    # make_mock_hassette provisions a real hassette-sync executor, so run_in_thread
    # can submit via loop.run_in_executor(hassette.sync_executor, ...) without raising.
    hassette = make_mock_hassette()
    bucket = TaskBucket(hassette)

    def sync_fn() -> None:
        raise TimeoutError("timed out")

    adapted = bucket.make_async_adapter(sync_fn)

    with pytest.raises(TimeoutError):
        await adapted()
