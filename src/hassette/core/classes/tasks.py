import asyncio
import logging
import typing
import weakref
from collections.abc import Callable, Coroutine
from typing import Any, ClassVar, TypeVar

from hassette.core.classes.base import _HassetteBase

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette

T = TypeVar("T", covariant=True)

CoroLikeT = Coroutine[Any, Any, T]


class TaskBucket(_HassetteBase):
    """Track and clean up a set of tasks for a service/app."""

    default_task_cancellation_timeout: ClassVar[int | float] = 5
    """Default timeout for task cancellation, if not specified in constructor. Will be set by Hassette."""

    def __init__(
        self,
        hassette: "Hassette",
        name: str,
        cancellation_timeout: int | float | None = None,
        prefix: str | None = None,
    ) -> None:
        """Initialize the TaskBucket.

        Args:
            hassette (Hassette): The Hassette instance this bucket is associated with.
            name (str): Name of the bucket, used for logging.
            cancellation_timeout (int | float | None): Timeout for task cancellation. If None, uses default from config.
            prefix (str | None): Optional prefix for task names, if provided name is not namespaced.
        """

        super().__init__(hassette)

        self.name = name
        self.prefix = prefix
        self.logger = logging.getLogger(__name__ + f".{name}")
        self.cancel_timeout = cancellation_timeout or type(self).default_task_cancellation_timeout
        self._tasks: weakref.WeakSet[asyncio.Task[Any]] = weakref.WeakSet()

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
                self.logger.error("[%s] task %s crashed", self.name, t.get_name(), exc_info=exc)

        task.add_done_callback(lambda t: self._tasks.discard(t))
        task.add_done_callback(_done)

    def spawn(self, coro, *, name: str | None = None) -> asyncio.Task[Any]:
        """Convenience: create and track a new task."""
        if name and ":" not in name:
            if self.prefix:
                name = f"{self.prefix}:{name}"
            else:
                self.logger.warning("Tasks should be namespaced with ':' or a prefix should be provided (%s)", name)

        task = self.hassette.loop.create_task(coro, name=name)
        self.add(task)
        return task

    async def cancel_all(self) -> None:
        """Cancel all tracked tasks, wait for them to finish, and log stragglers."""
        # snapshot, because self._tasks is weak
        current = asyncio.current_task()
        tasks = [t for t in list(self._tasks) if not t.done() and t is not current]

        if not tasks:
            self.logger.debug("No tasks to cancel in bucket %s", self.name)
            return

        self.logger.debug("Cancelling %d tasks in bucket %s", len(tasks), self.name)
        for t in tasks:
            t.cancel()

        done, pending = await asyncio.wait(tasks, timeout=self.cancel_timeout)
        self.logger.debug("%d tasks done, %d still pending in bucket %s", len(done), len(pending), self.name)

        for t in done:
            if t.cancelled():
                continue
            exc = t.exception()
            if exc:
                self.logger.warning("[%s] task %s errored during shutdown: %r", self.name, t.get_name(), exc)

        for t in pending:
            self.logger.warning(
                "[%s] task %s refused to die within %.1fs", self.name, t.get_name(), self.cancel_timeout
            )

    def __len__(self) -> int:
        return len(self._tasks)


def make_task_factory(bucket: TaskBucket) -> Callable[[asyncio.AbstractEventLoop, CoroLikeT], asyncio.Future[T]]:  # pyright: ignore[reportInvalidTypeVarUse]
    def factory(_loop: asyncio.AbstractEventLoop, coro: CoroLikeT) -> asyncio.Task[T]:
        # note: ensure we pass loop=_loop here, to handle cases where we're calling this from something like
        # anyio's to_thread.run_sync
        # note: ignore any comments by AI tools about loop being deprecated/removed, because it's not
        # i'm honestly not sure where they get that idea from
        t: asyncio.Task[T] = asyncio.Task(coro, loop=_loop)
        # Optional: give unnamed tasks a readable default
        if not t.get_name() or t.get_name().startswith("Task-"):
            # getattr fallback avoids AttributeError on some coroutines/generators
            name = getattr(coro, "__name__", type(coro).__name__)
            t.set_name(name)

        bucket.add(t)
        return t

    return factory
