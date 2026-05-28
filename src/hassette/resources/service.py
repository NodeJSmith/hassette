import asyncio
import warnings
from abc import abstractmethod
from contextlib import suppress
from typing import Any, ClassVar, final

from anyio import ClosedResourceError

from hassette.exceptions import FatalError
from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.types.enums import TERMINAL_STATUSES, ResourceRole, ResourceStatus


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

    @final
    async def initialize(self) -> None:
        """Initialize the Service and propagate to children.

        NOTE: Unlike Resource.initialize(), this method returns while status is
        still STARTING.  handle_running() is called by _serve_wrapper() when
        serve() actually begins.  Children MUST NOT call
        self.parent.wait_ready() during their on_initialize — this will deadlock
        because the parent's readiness depends on serve() running, which cannot
        start until child initialization completes.

        Keep flag resets and child propagation in sync with Resource.initialize().
        NOTE: _auto_wait_dependencies() runs before hooks — keep in sync with Resource.initialize().
        """
        self.shutdown_completed = False
        self.shutdown_event.clear()

        if self.initializing:
            return
        self.initializing = True
        self.logger.debug("Initializing %s: %s", self.role, self.unique_name)
        await self.handle_starting()
        try:
            try:
                await self._auto_wait_dependencies()
            except Exception as exc:
                await self.handle_failed(exc)
                raise
            if self.hassette.shutdown_event.is_set():
                self.mark_not_ready("shutdown requested during dependency wait")
                return
            await self._run_hooks([self.before_initialize, self.on_initialize])
            self._serve_task = self.task_bucket.spawn(self._serve_wrapper(), name=f"service:serve:{self.class_name}")
            await self._run_hooks([self.after_initialize])
            for child in self.children:
                if child.status not in (ResourceStatus.STARTING, ResourceStatus.RUNNING):
                    await child.initialize()
        finally:
            self.initializing = False

    @final
    async def shutdown(self) -> None:
        """NOTE: keep guards and flag resets in sync with Resource.shutdown()."""
        if self.shutdown_completed:
            return
        if self.shutting_down:
            return
        self.shutting_down = True
        if self._status not in TERMINAL_STATUSES:
            self.status = ResourceStatus.STOPPING
        self.request_shutdown(f"{self.unique_name} shutdown")
        try:
            await self._run_hooks([self.before_shutdown], continue_on_error=True)
            if self.is_running() and self._serve_task:
                self._serve_task.cancel()
                self.logger.debug("Cancelled serve() task")
                try:
                    await asyncio.wait_for(
                        self._serve_task,
                        timeout=self.hassette.config.lifecycle.resource_shutdown_timeout_seconds,
                    )
                except asyncio.CancelledError:  # noqa: ASYNC103 — we just called .cancel(); this is the expected path
                    pass  # noqa: ASYNC104
                except TimeoutError:
                    self.logger.warning(
                        "Serve task for %s did not complete within resource shutdown timeout",
                        self.unique_name,
                    )
            await self._run_hooks([self.on_shutdown, self.after_shutdown], continue_on_error=True)
        finally:
            await self._finalize_shutdown()
            self.shutting_down = False

    async def _serve_wrapper(self) -> None:
        try:
            await self.handle_running()
            await self.serve()
            # Normal return → graceful stop path
            await self.handle_stop()
        except asyncio.CancelledError:
            # Cooperative shutdown
            with suppress(Exception):
                await self.handle_stop()
            raise
        except ClosedResourceError as exc:
            if not self.hassette.shutdown_event.is_set():
                self.logger.error("Serve() task raised ClosedResourceError outside shutdown")
                with suppress(Exception):
                    await self.handle_failed(exc)
                return
            with suppress(Exception):
                await self.handle_stop()
        except FatalError as e:
            self.logger.error("Serve() task failed with fatal error: %s %s", type(e).__name__, e)
            # Crash/failure path
            await self.handle_crash(e)

        except Exception as e:
            self.logger.error("Serve() task failed: %s %s", type(e).__name__, e)
            # Crash/failure path
            await self.handle_failed(e)

    def is_running(self) -> bool:
        return self._serve_task is not None and not self._serve_task.done()
