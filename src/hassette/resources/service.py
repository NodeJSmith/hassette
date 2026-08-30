import asyncio
import warnings
from abc import abstractmethod
from contextlib import suppress
from typing import Any, ClassVar

from anyio import ClosedResourceError

from hassette.exceptions import FatalError
from hassette.resources.base import Resource
from hassette.resources.lifecycle import (
    handle_crash,
    handle_failed,
    handle_running,
    handle_starting,
    handle_stop,
    hooks_pool_remaining,
    mark_not_ready,
)
from hassette.resources.operations import run_hooks
from hassette.resources.restart import RestartSpec
from hassette.resources.teardown import TeardownCause, TeardownReport, merge_teardown_reports
from hassette.types.enums import ResourceRole, ResourceStatus


class Service(Resource):
    """Base class for background services.

    Lifecycle (in execution order):
        initialize():
            before_initialize()  — overridable: wait for deps, prepare
            on_initialize()      — overridable: service-specific setup
            → serve task spawned
            after_initialize()   — overridable: finalize

        shutdown():
            before_shutdown()    — overridable: pre-stop signals
            → serve task cancelled
            on_shutdown()        — overridable: service-specific cleanup
            after_shutdown()     — overridable: post-cleanup

    Subclasses MUST implement serve(). All six hooks are available.

    Subclasses should declare ``restart_spec`` to specify their restart strategy::

        class MyService(Service):
            restart_spec = RestartSpec(restart_type=RestartType.PERMANENT)

    Concrete subclasses that do not declare ``restart_spec`` will emit a warning at
    class definition time, because silently inheriting the default profile can hide
    incorrect production behavior.
    """

    role: ClassVar[ResourceRole] = ResourceRole.SERVICE

    restart_spec: ClassVar[RestartSpec] = RestartSpec()
    """Restart strategy for this service. Declare on each concrete subclass."""

    _serve_task: asyncio.Task | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Only warn for concrete classes. Since FinalMeta doesn't inherit from ABCMeta,
        # __abstractmethods__ is not computed automatically. Instead, check for any
        # abstract methods declared directly on this class — if any exist, treat the
        # class as abstract/intermediate and skip the warning.
        has_abstract_methods = any(
            getattr(v, "__isabstractmethod__", False)
            for v in cls.__dict__.values()
            if callable(v) or isinstance(v, (staticmethod, classmethod, property))
        )
        if has_abstract_methods:
            return
        # Only warn if restart_spec was not declared directly on this class.
        if "restart_spec" not in cls.__dict__:
            warnings.warn(
                f"{cls.__name__} does not declare restart_spec. "
                f"Inheriting the default RestartSpec() may silently use the wrong restart strategy. "
                f"Declare restart_spec on {cls.__name__} explicitly.",
                UserWarning,
                stacklevel=2,
            )

    def _force_terminal(self) -> None:
        """Override to also cancel the serve task."""
        if self._serve_task and not self._serve_task.done():
            self._serve_task.cancel()
        super()._force_terminal()

    @abstractmethod
    async def serve(self) -> None:
        """Subclasses MUST override: run until cancelled or finished."""
        raise NotImplementedError

    async def _initialize_body(self) -> None:
        """Initialize the Service and propagate to children.

        NOTE: Unlike Resource._initialize_body(), this method returns while status is
        still STARTING.  handle_running() is called by _serve_wrapper() when
        serve() actually begins.  Children MUST NOT call
        self.parent.wait_ready() during their on_initialize — this will deadlock
        because the parent's readiness depends on serve() running, which cannot
        start until child initialization completes.

        Keep child propagation in sync with Resource._initialize_body().
        NOTE: _auto_wait_dependencies() runs before hooks — keep in sync with Resource.
        """
        self.logger.debug("Initializing %s: %s", self.role, self.unique_name)
        await handle_starting(self)
        try:
            await self._auto_wait_dependencies()
        except Exception as exc:
            await handle_failed(self, exc)
            raise
        if self.hassette.shutdown_event.is_set():
            mark_not_ready(self, "shutdown requested during dependency wait")
            return
        await run_hooks(self, [self.before_initialize, self.on_initialize])
        self._serve_task = self.task_bucket.spawn(self._serve_wrapper(), name=f"service:serve:{self.class_name}")
        await run_hooks(self, [self.after_initialize])
        for child in self.children:
            if child.status not in (ResourceStatus.STARTING, ResourceStatus.RUNNING):
                await child.initialize()

    async def _shutdown_body(self) -> TeardownReport:
        """NOTE: keep hook ordering in sync with Resource._shutdown_body()."""
        reports: list[TeardownReport] = []

        hook_errors = await run_hooks(
            self, [self.before_shutdown], continue_on_error=True, bound_to_shutdown_budget=True
        )
        if hook_errors:
            reports.append(
                TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_FAILED,), failed_operations=("before_shutdown",))
            )

        if self.is_running() and self._serve_task:
            self._serve_task.cancel()
            self.logger.debug("Cancelled serve() task")
            # Shares the hooks pool with before_shutdown (already ran) and on_shutdown/after_shutdown
            # (run next). A slow serve-wait squeezes later hooks, but can't starve the mandatory tail.
            timeout = hooks_pool_remaining(self)
            self.logger.debug(
                "%s: entering serve-task wait with %.2fs of hooks pool remaining",
                self.unique_name,
                timeout,
            )
            _done, pending = await asyncio.wait([self._serve_task], timeout=timeout)
            if pending:
                self.logger.warning(
                    "Serve task for %s did not complete within resource shutdown timeout",
                    self.unique_name,
                )
                reports.append(
                    TeardownReport(
                        causes=(TeardownCause.SERVE_TASK_PENDING,),
                        pending_tasks=(self._serve_task.get_name(),),
                    )
                )
            else:
                with suppress(BaseException):
                    self._serve_task.exception()

        hook_errors = await run_hooks(
            self, [self.on_shutdown, self.after_shutdown], continue_on_error=True, bound_to_shutdown_budget=True
        )
        if hook_errors:
            reports.append(
                TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_FAILED,), failed_operations=("shutdown_hooks",))
            )

        reports.append(await self._run_post_hook_shutdown_stage())

        return merge_teardown_reports(*reports)

    async def _serve_wrapper(self) -> None:
        try:
            await handle_running(self)
            await self.serve()
            # Normal return → graceful stop path
            await handle_stop(self)
        except asyncio.CancelledError:
            # Cooperative shutdown
            with suppress(Exception):
                await handle_stop(self)
            raise
        except ClosedResourceError as exc:
            if not self.hassette.shutdown_event.is_set():
                self.logger.error("Serve() task raised ClosedResourceError outside shutdown")
                with suppress(Exception):
                    await handle_failed(self, exc)
                return
            with suppress(Exception):
                await handle_stop(self)
        except FatalError as exc:
            self.logger.error("Serve() task failed with fatal error: %s %s", type(exc).__name__, exc)
            # Crash/failure path
            await handle_crash(self, exc)

        except Exception as exc:
            self.logger.error("Serve() task failed: %s %s", type(exc).__name__, exc)
            # Crash/failure path
            await handle_failed(self, exc)

    def is_running(self) -> bool:
        return self._serve_task is not None and not self._serve_task.done()
