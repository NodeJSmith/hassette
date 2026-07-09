import asyncio
import contextlib
import functools
import threading
import typing
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import Future
from concurrent.futures import TimeoutError as CfTimeoutError  # aliased to distinguish from builtin TimeoutError
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
from typing import Any, ParamSpec, TypeVar, cast, overload

from hassette import context as ctx
from hassette.resources.base import Resource
from hassette.types.types import LOG_LEVEL_TYPE, CoroLikeT
from hassette.utils.func_utils import is_async_callable

_CROSS_THREAD_SPAWN_TIMEOUT_SECS = 10.0


@dataclass
class SyncWorkerHandle:
    """Shared handle between the loop thread and a sync worker for thread-identity tracking.

    Created by ``run_in_thread`` on the loop thread and stored in ``SYNC_WORKER_HANDLE``.
    The worker thread sets ``handle.thread`` via closure; ``_execute`` reads it at the
    timeout site to check liveness.
    """

    thread: threading.Thread | None = None


SYNC_WORKER_HANDLE: ContextVar[SyncWorkerHandle | None] = ContextVar("sync_worker_handle", default=None)
"""Carries the worker handle for the current sync submission from the loop thread to _execute.

Set on the loop thread in ``run_in_thread`` immediately after creating the handle.
``_execute`` (same asyncio task, same context snapshot) reads this ContextVar to check
``handle.thread.is_alive()`` at the timeout site.

The worker accesses the handle via closure, not via this ContextVar.  The ContextVar exists so
that ``_execute`` (running on the loop thread, in the same asyncio task) can read back the
handle reference.
"""

if typing.TYPE_CHECKING:
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

    is_task_bucket = True

    _tasks: "set[asyncio.Task[Any]]"

    _exception_recorders: "list[ExceptionRecorderT]"
    """List of recorders called for each non-CancelledError task exception."""

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._exception_recorders = []
        self.mark_ready(reason="TaskBucket initialized")

    @property
    def config_cancel_timeout(self) -> int | float:
        """Return the task cancellation timeout from the config."""
        return self.hassette.config.lifecycle.task_cancellation_timeout_seconds

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config."""
        return self.hassette.config.logging.task_bucket

    def __bool__(self) -> bool:
        # truthiness should not trigger __len__
        return True

    def add(self, task: asyncio.Task[Any]) -> None:
        """Add a task to the bucket and attach exception logging."""
        self._tasks.add(task)

        def _done(t: asyncio.Task[Any]) -> None:
            try:
                exc = t.exception()
            except asyncio.CancelledError:  # noqa: ASYNC103 — cancelled task is expected, not an error
                return  # noqa: ASYNC104
            except Exception:
                return
            if exc:
                self.logger.error("[%s] task %s crashed", self.unique_name, t.get_name(), exc_info=exc)
                for recorder in list(self._exception_recorders):
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

        Multiple recorders may be installed; all are called in installation order
        (FIFO) when an exception occurs.

        Args:
            recorder: Callable ``(task, exc) -> None`` invoked on each non-cancellation
                exception.
        """
        self._exception_recorders.append(recorder)

    def uninstall_exception_recorder(self, recorder: "ExceptionRecorderT") -> None:
        """Remove a previously installed exception recorder.

        Safe to call even if the recorder was never installed — it is a no-op in
        that case. Removes the first occurrence; assumes each installed recorder
        is a distinct callable.

        Args:
            recorder: The recorder callable to remove.
        """
        with contextlib.suppress(ValueError):
            self._exception_recorders.remove(recorder)

    def spawn(self, coro: CoroLikeT[T], *, name: str | None = None) -> asyncio.Task[T]:
        """Convenience: create and track a new task."""
        if name is None:
            name = getattr(coro, "__qualname__", None) or repr(coro)
        self.logger.debug("Spawning task %s in bucket %s", name, self.unique_name)
        current_thread = threading.get_ident()

        if current_thread == self.hassette.loop_thread_id:
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
                    self.hassette.loop_thread_id,
                )
            # Cross-thread: create the task on the real loop thread and wait for the handle
            result: Future[asyncio.Task[T]] = Future()

            def _create() -> None:
                try:
                    with ctx.use_task_bucket(self):
                        task = asyncio.create_task(coro, name=name)
                    result.set_result(task)
                except Exception as exc:
                    result.set_exception(exc)

            self.hassette.loop.call_soon_threadsafe(_create)
            try:
                return result.result(timeout=_CROSS_THREAD_SPAWN_TIMEOUT_SECS)
            except CfTimeoutError:
                self.logger.error(
                    "Cross-thread spawn of '%s' timed out after %.0fs waiting for the event loop",
                    name,
                    _CROSS_THREAD_SPAWN_TIMEOUT_SECS,
                )
                raise RuntimeError(
                    f"Cross-thread spawn of '{name}' timed out waiting for the event loop "
                    "— the loop may have stopped or is severely congested"
                ) from None

    def run_in_thread(self, fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> "asyncio.Future[R]":
        """Run a synchronous function on the dedicated sync-handler executor.

        Routes sync user code (handlers, jobs, App lifecycle hooks) through
        ``hassette.sync_executor`` (an
        :class:`~hassette.task_bucket.interruptible_executor.InterruptibleThreadPoolExecutor`)
        so that slow sync handlers are isolated from framework-internal
        ``asyncio.to_thread`` calls (logging, database), which continue using the
        loop-default executor.

        **Context propagation:** ``loop.run_in_executor`` does NOT copy the calling
        thread's contextvars into the worker (unlike ``asyncio.to_thread``).  This
        method captures a full snapshot via ``contextvars.copy_context()`` and runs
        *fn* inside it so that all contextvars set on the loop thread are visible to
        sync user code.

        **Thread handle:** see :class:`SyncWorkerHandle` and :data:`SYNC_WORKER_HANDLE`
        for the shared-handle mechanism used by the timeout site.

        Args:
            fn: The synchronous function to run.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            An :class:`asyncio.Future` that resolves to the return value of *fn*.
        """
        parent_ctx = copy_context()
        handle = SyncWorkerHandle()
        SYNC_WORKER_HANDLE.set(handle)

        def _call() -> R:
            handle.thread = threading.current_thread()
            return parent_ctx.run(fn, *args, **kwargs)

        # Submit to the dedicated executor so sync user code is isolated from
        # framework-internal asyncio.to_thread calls (logging, database).
        # loop.run_in_executor returns an asyncio.Future (awaitable) — callers
        # that do ``await self.run_in_thread(...)`` work identically to before.
        loop = asyncio.get_running_loop()
        future: asyncio.Future[R] = loop.run_in_executor(self.hassette.sync_executor, _call)

        # Submission-time saturation check: track the active worker count and emit a
        # rate-limited WARNING if the pool is approaching its ceiling.
        # The periodic probe in SyncExecutorService.serve() covers the case where
        # submissions stop (fully-starved pool); this check catches the rising-load
        # signal on each new submission.
        try:
            executor_service = self.hassette.sync_executor_service
        except RuntimeError:
            # The property raises RuntimeError until wire_services() wires the service
            # (early startup, or unit tests that never construct it).
            executor_service = None
        if executor_service is not None:
            executor_service.track_submission(cast("asyncio.Future[Any]", future))

        return future

    def post_to_loop(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
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
            except TimeoutError:
                raise
            except Exception:
                self.logger.exception("Error in sync function '%s'", getattr(fn, "__name__", repr(fn)))
                raise

        return _sync_fn

    def run_sync(self, fn: Coroutine[Any, Any, R], timeout_seconds: int | float | None = None) -> R:
        """Run an async function in a synchronous context.

        Args:
            fn: The async function to run.
            timeout_seconds: The timeout for the function call. ``None`` uses the config value;
                ``0`` fails immediately.

        Returns:
            The result of the function call.
        """

        if timeout_seconds is None:
            timeout_seconds = self.hassette.config.lifecycle.run_sync_timeout_seconds

        # Name the wrapped coroutine (e.g. "Api.call_service") for error and log context; the
        # traceback shows the facade method that delegated here.
        label = getattr(fn, "__qualname__", None) or getattr(fn, "__name__", repr(fn))

        # If we're already in an event loop, don't allow blocking calls.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass  # not in a loop -> safe to block
        else:
            fn.close()  # close the coroutine to avoid warnings
            raise RuntimeError(
                f"This sync method ({label}) was called from within an event loop. Use the async method instead."
            )

        fut: Future[R] | None = None
        try:
            fut = asyncio.run_coroutine_threadsafe(fn, self.hassette.loop)
            return fut.result(timeout=timeout_seconds)
        except CfTimeoutError:
            self.logger.exception("Sync function '%s' timed out", label)
            raise
        except Exception:
            self.logger.exception("Failed to run sync function '%s'", label)
            raise
        finally:
            if fut is not None and not fut.done():
                fut.cancel()

    async def run_on_loop_thread(self, fn: typing.Callable[..., R], *args: Any, **kwargs: Any) -> R:
        """Run a synchronous function on the main event loop thread.

        This is useful for ensuring that loop-affine code runs in the correct context.
        """
        fut = self.hassette.loop.create_future()

        def _call() -> None:
            try:
                fut.set_result(fn(*args, **kwargs))
            except Exception as exc:
                fut.set_exception(exc)

        self.hassette.loop.call_soon_threadsafe(_call)
        return await fut

    def create_task_on_loop(self, coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task[Any]:
        """Create a task on the main event loop thread, in this bucket's context."""
        with ctx.use_task_bucket(self):
            return self.hassette.loop.create_task(coro, name=name)

    def pending_tasks(self) -> list[asyncio.Task[Any]]:
        """Return a snapshot list of non-completed tasks in this bucket.

        This is the recommended public accessor for drain helpers and test
        infrastructure. Returns a fresh list so callers can safely iterate after
        mutations to the internal set without risking a ``RuntimeError``.

        Returns:
            A list of tasks that are currently running (not yet done).
        """
        return [t for t in list(self._tasks) if not t.done()]

    def cancel_all_sync(self) -> None:
        """Cancel all tracked tasks without awaiting completion (fire-and-forget)."""
        current = asyncio.current_task()
        tasks = [t for t in list(self._tasks) if not t.done() and t is not current]
        for t in tasks:
            t.cancel()

    async def cancel_all(self) -> None:
        """Cancel all tracked tasks, wait for them to finish, and log stragglers."""
        # snapshot to avoid mutation during iteration
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
    def factory(loop: asyncio.AbstractEventLoop, coro: CoroLikeT, **kwargs: Any) -> asyncio.Task[Any]:
        """A task factory that assigns tasks to the current context's bucket, or a global bucket.

        Python 3.14 changed create_task() to forward **kwargs (including ``name``)
        to the task factory. We pop ``name`` and apply it after construction so the
        auto-naming fallback still works for callers that don't pass one.
        """

        # note: ensure we pass loop=loop here, to handle cases where we're calling this from something like
        # anyio's to_thread.run_sync
        # note: ignore any comments by AI tools about loop being deprecated/removed, because it's not
        # i'm honestly not sure where they get that idea from
        explicit_name = kwargs.pop("name", None)
        t: asyncio.Task[Any] = asyncio.Task(coro, loop=loop, **kwargs)
        if explicit_name is not None:
            t.set_name(explicit_name)
        elif not t.get_name() or t.get_name().startswith("Task-"):
            # getattr fallback avoids AttributeError on some coroutines/generators
            name = getattr(coro, "__name__", type(coro).__name__)
            t.set_name(name)

        # compare using `is not None` to avoid `__len__` being called to determine truthiness
        current_bucket = ctx.CURRENT_BUCKET.get()
        owner = current_bucket if current_bucket is not None else global_bucket
        owner.add(t)
        return t

    return factory


Resource.register_task_bucket_factory(lambda hassette, owner: TaskBucket(hassette, parent=owner))
