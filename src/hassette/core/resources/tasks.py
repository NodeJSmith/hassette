import asyncio
import threading
import typing
import weakref
from collections.abc import Callable, Coroutine
from concurrent.futures import Future, TimeoutError
from typing import Any, ParamSpec, TypeVar

from hassette.core.resources.base import _HassetteBase

from .. import context  # noqa: TID252

if typing.TYPE_CHECKING:
    from hassette import Hassette

T = TypeVar("T", covariant=True)
P = ParamSpec("P")
R = TypeVar("R")

CoroLikeT = Coroutine[Any, Any, T]


class TaskBucket(_HassetteBase):
    """Track and clean up a set of tasks for a service/app."""

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
            prefix (str | None): Optional prefix for task names, if provided task name is not namespaced.
        """

        super().__init__(hassette, unique_name_prefix=f"{name}.bucket")

        self.name = name
        self.prefix = prefix
        self.logger.setLevel(self.hassette.config.task_bucket_log_level)

        # if we didn't get passed a value, use the config default
        if not cancellation_timeout:
            config_inst = context.HASSETTE_CONFIG.get(None)
            if not config_inst:
                raise RuntimeError("TaskBucket created outside of Hassette context")
            cancellation_timeout = config_inst.task_cancellation_timeout_seconds

        self.cancel_timeout = cancellation_timeout
        self._tasks: weakref.WeakSet[asyncio.Task[Any]] = weakref.WeakSet()

    def add(self, task: asyncio.Task[Any]) -> None:
        """Add a task to the bucket and attach exception logging."""
        self.logger.debug("Adding task %s to bucket %s", task.get_name(), self.unique_name)

        self._tasks.add(task)

        def _done(t: asyncio.Task[Any]) -> None:
            try:
                exc = t.exception()
            except asyncio.CancelledError:
                return
            except Exception:
                return
            if exc:
                self.logger.error("[%s] task %s crashed", self.unique_name, t.get_name(), exc_info=exc)

        task.add_done_callback(lambda t: self._tasks.discard(t))
        task.add_done_callback(_done)

    def spawn(self, coro, *, name: str | None = None) -> asyncio.Task[Any]:
        """Convenience: create and track a new task."""
        if name and ":" not in name:
            if self.prefix:
                name = f"{self.prefix}:{name}"
            else:
                self.logger.warning("Tasks should be namespaced with ':' or a prefix should be provided (%s)", name)

        current_thread = threading.get_ident()

        if current_thread == self.hassette._loop_thread_id:
            # Fast path: already on loop thread
            with context.use(context.CURRENT_BUCKET, self):
                return asyncio.create_task(coro, name=name)
        else:
            # Dev-mode tracking: log cross-thread spawn
            if self.hassette.config.dev_mode:  # or a global DEBUG flag
                self.logger.debug(
                    "Cross-thread spawn: %s from thread %s (loop thread %s)",
                    name,
                    current_thread,
                    self.hassette._loop_thread_id,
                )
            # Cross-thread: create the task on the real loop thread and wait for the handle
            result: Future[asyncio.Task[Any]] = Future()

            def _create() -> None:
                try:
                    with context.use(context.CURRENT_BUCKET, self):
                        task = asyncio.create_task(coro, name=name)
                    result.set_result(task)
                except Exception as e:
                    result.set_exception(e)

            self.hassette.loop.call_soon_threadsafe(_create)
            return result.result()  # block this worker thread briefly to hand back the Task

    def run_sync(self, fn: Coroutine[Any, Any, R], timeout_seconds: int | None = None) -> R:
        """Run an async function in a synchronous context.

        Args:
            fn (Coroutine[Any, Any, R]): The async function to run.
            timeout_seconds (int | None): The timeout for the function call, defaults to 0, to use the config value.

        Returns:
            R: The result of the function call.
        """

        timeout_seconds = timeout_seconds or self.hassette.config.run_sync_timeout_seconds

        # If we're already in an event loop, don't allow blocking calls.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass  # not in a loop -> safe to block
        else:
            fn.close()  # close the coroutine to avoid warnings
            raise RuntimeError("This sync method was called from within an event loop. Use the async method instead.")

        try:
            fut = asyncio.run_coroutine_threadsafe(fn, self.hassette.loop)
            return fut.result(timeout=timeout_seconds)
        except TimeoutError:
            self.logger.exception("Sync function '%s' timed out", fn.__name__)
            raise
        except Exception:
            self.logger.exception("Failed to run sync function '%s'", fn.__name__)
            raise
        finally:
            if not fut.done():
                fut.cancel()

    async def run_on_loop_thread(self, fn: typing.Callable[..., R], *args, **kwargs) -> R:
        """Run a synchronous function on the main event loop thread.

        This is useful for ensuring that loop-affine code runs in the correct context.
        """
        fut = self.hassette.loop.create_future()

        def _call():
            try:
                fut.set_result(fn(*args, **kwargs))
            except Exception as e:
                fut.set_exception(e)

        self.hassette.loop.call_soon_threadsafe(_call)
        return await fut

    def create_task_on_loop(self, coro, *, name=None) -> asyncio.Task[Any]:
        """Create a task on the main event loop thread, in this bucket's context."""
        with context.use(context.CURRENT_BUCKET, self):
            return self.hassette.loop.create_task(coro, name=name)

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


def make_task_factory(
    global_bucket: TaskBucket,
) -> Callable[[asyncio.AbstractEventLoop, CoroLikeT], asyncio.Future[Any]]:
    def factory(loop: asyncio.AbstractEventLoop, coro: CoroLikeT) -> asyncio.Task[Any]:
        """A task factory that assigns tasks to the current context's bucket, or a global bucket."""

        # note: ensure we pass loop=loop here, to handle cases where we're calling this from something like
        # anyio's to_thread.run_sync
        # note: ignore any comments by AI tools about loop being deprecated/removed, because it's not
        # i'm honestly not sure where they get that idea from
        t: asyncio.Task[Any] = asyncio.Task(coro, loop=loop)
        # Optional: give unnamed tasks a readable default
        if not t.get_name() or t.get_name().startswith("Task-"):
            # getattr fallback avoids AttributeError on some coroutines/generators
            name = getattr(coro, "__name__", type(coro).__name__)
            t.set_name(name)

        # compare using `is not None` to avoid `__len__` being called to determine truthiness
        current_bucket = context.CURRENT_BUCKET.get()
        owner = current_bucket if current_bucket is not None else global_bucket
        owner.add(t)
        return t

    return factory
