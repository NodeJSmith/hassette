import asyncio
import functools
import threading
import typing
import weakref
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import Future, TimeoutError
from typing import Any, ParamSpec, TypeVar, cast, overload

from hassette import context as ctx
from hassette.resources.base import Resource
from hassette.types.types import LOG_LEVEL_TYPE, CoroLikeT
from hassette.utils.func_utils import is_async_callable

if typing.TYPE_CHECKING:
    from contextvars import Context
    from types import CoroutineType

    from hassette import Hassette

T = TypeVar("T")
P = ParamSpec("P")
R = TypeVar("R")

ExceptionRecorderT = Callable[[asyncio.Task[Any], BaseException], None]
"""Callback signature for recording task exceptions during drain.

Called by ``TaskBucket._done`` when a tracked task completes with a
non-cancellation exception. See :meth:`TaskBucket.install_exception_recorder`.
"""


class TaskBucket(Resource):
    """Track and clean up a set of tasks for a service/app."""

    _tasks: "weakref.WeakSet[asyncio.Task[Any]]"
    """Weak set of tasks tracked by this bucket."""

    _exception_recorder: "ExceptionRecorderT | None"
    """Optional recorder called on each non-CancelledError task exception."""

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._tasks = weakref.WeakSet()
        self._exception_recorder = None
        self.mark_ready(reason="TaskBucket initialized")

    @property
    def config_cancel_timeout(self) -> int | float:
        """Return the task cancellation timeout from the config."""
        return self.hassette.config.task_cancellation_timeout_seconds

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config."""
        return self.hassette.config.task_bucket_log_level

    def __bool__(self) -> bool:
        # truthiness should not trigger __len__
        return True

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
                self.logger.error("[%s] task %s crashed", self.unique_name, t.get_name(), exc_info=exc)
                recorder = self._exception_recorder
                if recorder is not None:
                    try:
                        recorder(t, exc)
                    except Exception:
                        self.logger.exception(
                            "[%s] exception recorder failed for task %s",
                            self.unique_name,
                            t.get_name(),
                        )

        task.add_done_callback(lambda t: self._tasks.discard(t))
        task.add_done_callback(_done)

    def install_exception_recorder(self, recorder: "ExceptionRecorderT") -> None:
        """Install a callback that is called for each non-CancelledError task exception.

        Called from the task's done callback, after the error is logged.
        The recorder receives the completed task and the exception.

        Intended for test infrastructure (e.g., AppTestHarness drain) that needs to
        collect task exceptions regardless of whether the task completed during a
        ``asyncio.wait`` call or between iterations.

        Args:
            recorder: Callable ``(task, exc) -> None`` invoked on each non-cancellation
                exception. Only one recorder can be installed at a time; calling this a
                second time replaces the previous recorder.
        """
        self._exception_recorder = recorder

    def uninstall_exception_recorder(self) -> None:
        """Remove the installed exception recorder (no-op if none installed)."""
        self._exception_recorder = None

    def spawn(self, coro: CoroLikeT[T], *, name: str | None = None) -> asyncio.Task[T]:
        """Convenience: create and track a new task."""
        self.logger.debug("Spawning task %s in bucket %s", name or repr(coro), self.unique_name)
        current_thread = threading.get_ident()

        if current_thread == self.hassette._loop_thread_id:
            # Fast path: already on loop thread
            with ctx.use_task_bucket(self):
                return asyncio.create_task(coro, name=name)
        else:
            # Dev-mode tracking: log cross-thread spawn
            if self.hassette.config.dev_mode:
                self.logger.debug(
                    "Cross-thread spawn: %s from thread %s (loop thread %s)",
                    name,
                    current_thread,
                    self.hassette._loop_thread_id,
                )
            # Cross-thread: create the task on the real loop thread and wait for the handle
            result: Future[asyncio.Task[T]] = Future()

            def _create() -> None:
                try:
                    with ctx.use_task_bucket(self):
                        task = asyncio.create_task(coro, name=name)
                    result.set_result(task)
                except Exception as e:
                    result.set_exception(e)

            self.hassette.loop.call_soon_threadsafe(_create)
            return result.result()  # block this worker thread briefly to hand back the Task

    def run_in_thread(self, fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> "CoroutineType[Any, Any, R]":
        """Run a synchronous function in a separate thread.

        This is a thin wrapper around `asyncio.to_thread`, but ensures that the current TaskBucket context
        is preserved in the new thread.

        Args:
            fn: The synchronous function to run.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            A Future representing the result of the function call.
        """
        current_bucket = ctx.CURRENT_BUCKET.get()

        def _call() -> R:
            if current_bucket is not None:
                with ctx.use_task_bucket(current_bucket):
                    return fn(*args, **kwargs)
            else:
                return fn(*args, **kwargs)

        return asyncio.to_thread(_call)

    def post_to_loop(self, fn, *args, **kwargs) -> None:
        """Schedule a callable on the event loop from any thread."""
        self.hassette.loop.call_soon_threadsafe(fn, *args, **kwargs)

    @overload
    def make_async_adapter(self, fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]: ...
    @overload
    def make_async_adapter(self, fn: Callable[P, R]) -> Callable[P, Awaitable[R]]: ...

    def make_async_adapter(self, fn: Callable[P, R] | Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        """
        Normalize a callable (sync or async) into an async callable with the same signature.

        - If `fn` is async: await it.
        - If `fn` is sync: run it in Hassette's thread pool executor via TaskBucket.run_in_thread.
        """
        if is_async_callable(fn):

            @functools.wraps(cast("Callable[..., object]", fn))
            async def _async_fn(*args: P.args, **kwargs: P.kwargs) -> R:
                return await cast("Callable[P, Awaitable[R]]", fn)(*args, **kwargs)

            return _async_fn

        @functools.wraps(cast("Callable[..., object]", fn))
        async def _sync_fn(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await self.run_in_thread(cast("Callable[P, R]", fn), *args, **kwargs)
            except Exception:
                # optional: you can re-raise without cancelling; no task to cancel anymore
                self.logger.exception("Error in sync function '%s'", getattr(fn, "__name__", repr(fn)))
                raise

        return _sync_fn

    def run_sync(self, fn: Coroutine[Any, Any, R], timeout_seconds: int | None = None) -> R:
        """Run an async function in a synchronous context.

        Args:
            fn: The async function to run.
            timeout_seconds: The timeout for the function call, defaults to 0, to use the config value.

        Returns:
            The result of the function call.
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
        with ctx.use_task_bucket(self):
            return self.hassette.loop.create_task(coro, name=name)

    def pending_tasks(self) -> list[asyncio.Task[Any]]:
        """Return a snapshot list of non-completed tasks in this bucket.

        This is the recommended public accessor for drain helpers and test
        infrastructure. Returns a fresh list so callers can safely iterate after
        mutations to the internal WeakSet without risking a ``RuntimeError``.

        Returns:
            A list of tasks that are currently running (not yet done).
        """
        return [t for t in list(self._tasks) if not t.done()]

    def cancel_all_sync(self) -> None:
        """Cancel all tracked tasks without awaiting completion (fire-and-forget).

        Snapshots the WeakSet before iterating to avoid mutation during iteration.
        """
        current = asyncio.current_task()
        tasks = [t for t in list(self._tasks) if not t.done() and t is not current]
        for t in tasks:
            t.cancel()

    async def cancel_all(self) -> None:
        """Cancel all tracked tasks, wait for them to finish, and log stragglers."""
        # snapshot, because self._tasks is weak
        current = asyncio.current_task()
        tasks = [t for t in list(self._tasks) if not t.done() and t is not current]

        if not tasks:
            self.logger.debug("No tasks to cancel in bucket %s", self.unique_name)
            return

        self.logger.debug("Cancelling %d tasks in bucket %s", len(tasks), self.unique_name)
        for t in tasks:
            t.cancel()

        done, pending = await asyncio.wait(tasks, timeout=self.config_cancel_timeout)
        self.logger.debug("%d tasks done, %d still pending in bucket %s", len(done), len(pending), self.unique_name)

        for t in done:
            if t.cancelled():
                continue
            exc = t.exception()
            if exc:
                self.logger.warning("[%s] task %s errored during shutdown: %r", self.unique_name, t.get_name(), exc)

        for t in pending:
            self.logger.warning(
                "[%s] task %s refused to die within %.1fs", self.unique_name, t.get_name(), self.config_cancel_timeout
            )

    def __len__(self) -> int:
        return len(self._tasks)


def make_task_factory(
    global_bucket: TaskBucket,
) -> Callable[[asyncio.AbstractEventLoop, CoroLikeT], asyncio.Future[Any]]:
    def factory(
        loop: asyncio.AbstractEventLoop, coro: CoroLikeT, context: "Context | None" = None
    ) -> asyncio.Task[Any]:
        """A task factory that assigns tasks to the current context's bucket, or a global bucket."""

        # note: ensure we pass loop=loop here, to handle cases where we're calling this from something like
        # anyio's to_thread.run_sync
        # note: ignore any comments by AI tools about loop being deprecated/removed, because it's not
        # i'm honestly not sure where they get that idea from
        t: asyncio.Task[Any] = asyncio.Task(coro, loop=loop, context=context)
        # Optional: give unnamed tasks a readable default
        if not t.get_name() or t.get_name().startswith("Task-"):
            # getattr fallback avoids AttributeError on some coroutines/generators
            name = getattr(coro, "__name__", type(coro).__name__)
            t.set_name(name)

        # compare using `is not None` to avoid `__len__` being called to determine truthiness
        current_bucket = ctx.CURRENT_BUCKET.get()
        owner = current_bucket if current_bucket is not None else global_bucket
        owner.add(t)
        return t

    return factory
