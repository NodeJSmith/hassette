"""Tests for contextvar propagation through TaskBucket.run_in_thread.

Covers:
- HASSETTE_INSTANCE is visible in the worker thread.
- HASSETTE_CONFIG is visible in the worker thread.
- CURRENT_BUCKET is visible in the worker thread.
- CURRENT_EXECUTION_ID is visible in the worker thread.
- SYNC_WORKER_CELL still works after the context-propagation change.
"""

import threading
from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest

from hassette import context as ctx
from hassette.task_bucket.task_bucket import SYNC_WORKER_CELL, TaskBucket
from hassette.test_utils import make_mock_hassette


@pytest.fixture
def hassette_mock() -> Iterator[AsyncMock]:
    hassette = make_mock_hassette()
    token = ctx.HASSETTE_INSTANCE.set(hassette)
    config_token = ctx.HASSETTE_CONFIG.set(hassette.config)
    try:
        yield hassette
    finally:
        ctx.HASSETTE_CONFIG.reset(config_token)
        ctx.HASSETTE_INSTANCE.reset(token)
        hassette.sync_executor.shutdown(join_threads_or_timeout=True)


@pytest.fixture
def bucket(hassette_mock: AsyncMock) -> TaskBucket:
    return TaskBucket(hassette_mock)


async def test_hassette_instance_visible_in_worker(hassette_mock: AsyncMock, bucket: TaskBucket) -> None:
    """get_hassette() returns the correct instance inside run_in_thread."""
    captured: list[object] = []

    def read_hassette() -> None:
        captured.append(ctx.get_hassette())

    await bucket.run_in_thread(read_hassette)

    assert len(captured) == 1
    assert captured[0] is hassette_mock


async def test_hassette_config_visible_in_worker(hassette_mock: AsyncMock, bucket: TaskBucket) -> None:
    """get_hassette_config() returns the correct config inside run_in_thread."""
    captured: list[object] = []

    def read_config() -> None:
        captured.append(ctx.get_hassette_config())

    await bucket.run_in_thread(read_config)

    assert len(captured) == 1
    assert captured[0] is hassette_mock.config


async def test_current_bucket_visible_in_worker(bucket: TaskBucket) -> None:
    """CURRENT_BUCKET is propagated so spawned sub-tasks route to the correct bucket."""
    captured: list[object] = []

    with ctx.use_task_bucket(bucket):

        def read_bucket() -> None:
            captured.append(ctx.CURRENT_BUCKET.get())

        await bucket.run_in_thread(read_bucket)

    assert len(captured) == 1
    assert captured[0] is bucket


async def test_execution_id_visible_in_worker(bucket: TaskBucket) -> None:
    """CURRENT_EXECUTION_ID is propagated to the worker thread."""
    captured: list[str | None] = []
    test_id = "test-execution-id"

    with ctx.use(ctx.CURRENT_EXECUTION_ID, test_id):

        def read_execution_id() -> None:
            captured.append(ctx.CURRENT_EXECUTION_ID.get())

        await bucket.run_in_thread(read_execution_id)

    assert len(captured) == 1
    assert captured[0] == test_id


async def test_worker_contextvar_writes_do_not_leak_back(bucket: TaskBucket) -> None:
    """ContextVar mutations inside the worker stay in the worker's copy."""
    original_id = ctx.CURRENT_EXECUTION_ID.get(None)

    def mutate_execution_id() -> None:
        ctx.CURRENT_EXECUTION_ID.set("mutated-in-worker")

    await bucket.run_in_thread(mutate_execution_id)

    assert ctx.CURRENT_EXECUTION_ID.get(None) == original_id


async def test_sync_worker_cell_still_works(bucket: TaskBucket) -> None:
    """The SYNC_WORKER_CELL thread-capture mechanism is unaffected by context propagation."""

    def sync_fn() -> str:
        return "ok"

    future = bucket.run_in_thread(sync_fn)
    cell = SYNC_WORKER_CELL.get()
    assert cell is not None

    result = await future
    assert result == "ok"
    assert cell[0] is not None
    assert isinstance(cell[0], threading.Thread)
