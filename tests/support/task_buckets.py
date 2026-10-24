"""Test helpers for TaskBucket arrangements Hassette sets up at runtime."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import Mock

from hassette.core.sync_executor import SyncExecutor
from hassette.task_bucket import TaskBucket, make_task_factory
from tests.support.mock_hassette import make_mock_hassette


@contextmanager
def sealed_fallback_task_factory(bucket: TaskBucket | None = None) -> Iterator[None]:
    """Install a TaskBucket as the running loop's task-factory fallback for the wrapped block.

    The arrangement ``Hassette`` has during exit: its TaskBucket is the loop's fallback bucket (see
    ``make_task_factory``) and is sealed, so any task created through the loop with no bucket in
    context is rejected. With no ``bucket``, a fresh one is created already sealed; pass a resource's
    own bucket to have it sealed by that resource's shutdown instead.
    """
    if bucket is None:
        bucket = TaskBucket(make_mock_hassette(), sync_executor=Mock(spec=SyncExecutor))
        bucket.seal()
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    loop.set_task_factory(make_task_factory(bucket))  # pyright: ignore[reportArgumentType]
    try:
        yield
    finally:
        loop.set_task_factory(previous_factory)
