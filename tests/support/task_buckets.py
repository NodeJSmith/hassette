"""Test helpers for TaskBucket arrangements Hassette sets up at runtime."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock

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


def make_closing_task_bucket() -> MagicMock:
    """Build a task_bucket stub whose ``spawn()`` closes coroutines instead of running them.

    Every coroutine handed to ``spawn()`` is closed immediately so it is never reported as
    "never awaited", and the returned task mock reports ``done() is True``.

    Nothing is ever scheduled on the event loop, so reach for this when a test asserts on what
    was spawned rather than on its effects. Contrast ``tests.support.helpers.make_task_bucket``,
    which spawns real tasks.

    Timing caveat: ``add_done_callback`` invokes its callback synchronously, where a real
    completed future defers it through ``loop.call_soon``. A caller that decrements bookkeeping
    from that callback (e.g. ``BusService``'s dispatch-pending counter) still ends up balanced,
    but the ordering relative to surrounding awaits differs.
    """
    bucket = MagicMock()
    task = MagicMock()
    task.done.return_value = True
    task.add_done_callback.side_effect = lambda callback: callback(task)

    def _spawn(coro: object, **kwargs: object) -> MagicMock:  # noqa: ARG001
        if asyncio.iscoroutine(coro):
            coro.close()
        return task

    bucket.spawn.side_effect = _spawn
    return bucket
