import asyncio
import logging
import weakref
from collections.abc import Callable, Coroutine, Generator
from typing import Any, TypeVar

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")

CoroLikeT = Coroutine[Any, Any, T] | Generator[Any, None, T]


class TaskBucket:
    """Track and clean up a set of tasks for a service/app."""

    def __init__(self, name: str, cancellation_timeout: float | None = None) -> None:
        self.name = name
        self._cancel_timeout = cancellation_timeout
        self._tasks: weakref.WeakSet[asyncio.Task[Any]] = weakref.WeakSet()

    @property
    def cancel_timeout(self) -> float:
        """Return the configured task cancellation timeout, or the default from config."""
        from hassette.config.core_config import HassetteConfig

        if self._cancel_timeout is not None:
            return self._cancel_timeout

        self._cancel_timeout = HassetteConfig.get_config().task_cancellation_timeout_seconds

        return self._cancel_timeout

    def add(self, task: asyncio.Task[Any]) -> None:
        """Add a task to the bucket and attach exception logging."""
        self._tasks.add(task)

        def _done(t: asyncio.Task[Any]) -> None:
            try:
                exc = t.exception()
            except asyncio.CancelledError:
                return
            except Exception:
                return
            if exc:
                LOGGER.error("[%s] task %s crashed", self.name, t.get_name(), exc_info=exc)

        task.add_done_callback(lambda t: self._tasks.discard(t))
        task.add_done_callback(_done)

    def spawn(self, coro, *, name: str | None = None) -> asyncio.Task[Any]:
        """Convenience: create and track a new task."""
        task = asyncio.create_task(coro, name=name)
        self.add(task)
        return task

    async def cancel_all(self) -> None:
        """Cancel all tracked tasks, wait for them to finish, and log stragglers."""
        # snapshot, because self._tasks is weak
        current = asyncio.current_task()
        tasks = [t for t in list(self._tasks) if not t.done() and t is not current]
        if not tasks:
            return
        for t in tasks:
            t.cancel()
        done, pending = await asyncio.wait(tasks, timeout=self.cancel_timeout)
        for t in done:
            if t.cancelled():
                continue
            exc = t.exception()
            if exc:
                LOGGER.warning("[%s] task %s errored during shutdown: %r", self.name, t.get_name(), exc)
        for t in pending:
            LOGGER.warning("[%s] task %s refused to die within %.1fs", self.name, t.get_name(), self.cancel_timeout)

    def __len__(self) -> int:
        return len(self._tasks)


def make_task_factory(bucket: "TaskBucket") -> Callable[[asyncio.AbstractEventLoop, CoroLikeT], asyncio.Future[T]]:  # pyright: ignore[reportInvalidTypeVarUse]
    def factory(_: asyncio.AbstractEventLoop, coro: CoroLikeT) -> asyncio.Task[T]:
        t: asyncio.Task[T] = asyncio.Task(coro)

        # TODO: implement contextvars for metadata
        # tag metadata
        # t.owner = current_app.get(None)
        # t.request_id = request_id.get("-")
        # fallback name if user didn't set
        # if not t.get_name() or t.get_name().startswith("Task-"):
        #     t.set_name(f"{t.owner or 'anon'}:{coro.__name__}")
        # End TODO:

        # auto-track
        bucket.add(t)

        # log unhandled exceptions
        def _done(task: asyncio.Task[T]) -> None:
            try:
                exc = task.exception()
            except asyncio.CancelledError:
                return
            except Exception:
                return
            if exc:
                LOGGER.error("Task %s failed", task.get_name(), exc_info=exc)

        t.add_done_callback(_done)
        return t

    return factory
