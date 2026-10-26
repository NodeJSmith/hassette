import asyncio
from abc import abstractmethod
from contextlib import suppress
from typing import Any, ClassVar

from anyio import ClosedResourceError
from hassette_wire import ResourceStatus

from hassette.exceptions import FatalError, ServeEndedError
from hassette.resources.base import Resource
from hassette.resources.lifecycle import (
    handle_crash,
    handle_failed,
    handle_running,
    handle_starting,
    handle_stop,
    mark_not_ready,
)
from hassette.resources.operations import run_hooks, shutdown_hook_report
from hassette.resources.shutdown_deadline import format_bound, shutdown_hook_bound
from hassette.resources.teardown import TeardownCause, TeardownReport, merge_teardown_reports
from hassette.types.enums import ResourceRole


class Service(Resource):
    """Base class for background services.

    Lifecycle (in execution order):
        initialize():
            before_initialize()  — overridable: wait for deps, prepare
            on_initialize()      — overridable: service-specific setup
            after_initialize()   — overridable: finalize
            → children initialized
            → serve task spawned (status becomes RUNNING once it starts)

        shutdown():
            before_shutdown()    — overridable: pre-stop signals
            → serve task cancelled
            on_shutdown()        — overridable: service-specific cleanup
            after_shutdown()     — overridable: post-cleanup

    Subclasses MUST implement serve(). All six hooks are available.

    Every concrete subclass declares ``required`` in its own body::

        class MyService(Service):
            required = False

    A required service's ``serve()`` failure ends the process; an optional one's leaves the service
    FAILED (CRASHED for a ``FatalError``) until hassette restarts, with one ERROR saying so. Only a
    service whose parent is ``Hassette`` may be required: a service an app owns declares
    ``required = False``. Nothing restarts a service in-process.
    """

    role: ClassVar[ResourceRole] = ResourceRole.SERVICE

    required: ClassVar[bool] = True
    """Whether a ``serve()`` failure ends the process. Declare on each concrete subclass."""

    _serve_task: asyncio.Task | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Only enforce on concrete classes. Since FinalMeta doesn't inherit from ABCMeta,
        # __abstractmethods__ is not computed automatically. Instead, check for any
        # abstract methods declared directly on this class — if any exist, treat the
        # class as abstract/intermediate and skip the check.
        has_abstract_methods = any(
            getattr(v, "__isabstractmethod__", False)
            for v in cls.__dict__.values()
            if callable(v) or isinstance(v, (staticmethod, classmethod, property))
        )
        if has_abstract_methods:
            return
        if "required" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must declare whether it is required: set `required = True` (its failure ends "
                f"the process; framework services owned by Hassette only) or `required = False` in its class body."
            )

    @classmethod
    def _validate_parent(cls, parent: Resource) -> None:
        """Raise unless a required service's parent is ``Hassette``: only the root may end the process.

        ``Hassette`` is the one resource whose ``hassette`` is itself, so that identity test finds the root.
        """
        if cls.required and parent is not parent.hassette:
            raise ValueError(
                f"{cls.__name__} is a required service and can only be a child of Hassette, not "
                f"{parent.class_name}. A service owned by an app must declare `required = False`."
            )

    def _optional_serve_task(self) -> "asyncio.Task[None] | None":
        """This service's serve task if it is optional, else None."""
        return None if self.required else self._serve_task

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
        still STARTING.  Spawning serve() is its last step, with no await after it,
        so _serve_wrapper() sets RUNNING only after the whole body has completed:
        a failure in the body belongs to the initialization attempt, and a serve()
        failure never does.  Children and after_initialize() must not wait on this
        Service's serve() or readiness — serve() cannot start until they return.

        Keep child propagation in sync with Resource._initialize_body().
        NOTE: _auto_wait_dependencies() runs before hooks — keep in sync with Resource.
        """
        self.lifecycle_logger.debug("Initializing %s: %s", self.role, self.unique_name)
        await handle_starting(self)
        # Only Exception: a CancelledError here comes from cancel() or shutdown(), which own that
        # outcome, so the attempt is intentionally not marked FAILED or logged as a failure.
        try:
            await self._auto_wait_dependencies()
        except Exception as exc:
            await handle_failed(self, exc)
            raise
        if self.hassette.shutdown_event.is_set():
            mark_not_ready(self, "shutdown requested during dependency wait")
            return
        await run_hooks(
            self, [self._framework_before_hooks, self.before_initialize, self.on_initialize, self.after_initialize]
        )
        for child in self.children:
            if child.status not in (ResourceStatus.STARTING, ResourceStatus.RUNNING):
                await child.initialize()
        self._serve_task = self.task_bucket.spawn(self._serve_wrapper(), name=f"service:serve:{self.class_name}")

    async def _shutdown_body(self) -> TeardownReport:
        """NOTE: keep hook ordering in sync with Resource._shutdown_body()."""
        reports: list[TeardownReport] = []

        hook_errors = await run_hooks(self, [self.before_shutdown], continue_on_error=True, shutdown_bound=True)
        reports.append(shutdown_hook_report(hook_errors, "before_shutdown"))

        if self.is_running() and self._serve_task:
            self._serve_task.cancel()
            self.lifecycle_logger.debug("Cancelled serve() task")
            # Bounded like a hook: its own cancel-and-wait, clamped to the operation's deadline.
            timeout = shutdown_hook_bound(self)
            self.lifecycle_logger.debug(
                "%s: entering serve-task wait with %s bound", self.unique_name, format_bound(timeout)
            )
            _done, pending = await asyncio.wait([self._serve_task], timeout=timeout)
            if pending:
                self.lifecycle_logger.warning(
                    "Serve task for %s did not complete within its %s bound", self.unique_name, format_bound(timeout)
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
            self, [self.on_shutdown, self.after_shutdown], continue_on_error=True, shutdown_bound=True
        )
        reports.append(shutdown_hook_report(hook_errors, "shutdown_hooks"))

        reports.append(await self._run_post_hook_shutdown_stage())

        return merge_teardown_reports(*reports)

    async def _serve_wrapper(self) -> None:
        """Run ``serve()`` and record how it ended.

        Every failure exit reports to ``Hassette.report_service_failure()`` first, synchronously,
        before the status handlers await their telemetry sends: a stalled event channel must not
        delay the report that decides whether the process exits (spec 134 D8).

        The status handlers are suppressed where their send can't be trusted to work: on cancellation,
        so the cancellation is always re-raised, and on a closed stream, since the send would fail on
        that same stream. Elsewhere a failing send surfaces on the serve task like any other error.
        """
        try:
            await handle_running(self)
            await self.serve()
        except asyncio.CancelledError:
            if self.required and not self.stop_requested():
                exc = ServeEndedError(f"{self.class_name}.serve() was cancelled without a shutdown request")
                self.hassette.report_service_failure(self, exc)
                with suppress(Exception):
                    await handle_failed(self, exc)
            else:
                with suppress(Exception):
                    await handle_stop(self)
            raise
        except ClosedResourceError as exc:
            if self.stop_requested():
                with suppress(Exception):
                    await handle_stop(self)
                return
            self.hassette.report_service_failure(self, exc)
            self.lifecycle_logger.error("Serve() task raised ClosedResourceError outside shutdown")
            with suppress(Exception):
                await handle_failed(self, exc)
        except FatalError as exc:
            self.hassette.report_service_failure(self, exc)
            self.lifecycle_logger.error("Serve() task failed with fatal error: %s %s", type(exc).__name__, exc)
            await handle_crash(self, exc)
        except Exception as exc:
            self.hassette.report_service_failure(self, exc)
            self.lifecycle_logger.error("Serve() task failed: %s %s", type(exc).__name__, exc)
            await handle_failed(self, exc)
        else:
            # A required service can't stop silently: returning unasked is a failure (spec 134 D8). An
            # optional service that returns just has nothing left to do.
            if self.required and not self.stop_requested():
                exc = ServeEndedError(f"{self.class_name}.serve() returned without a shutdown request")
                self.hassette.report_service_failure(self, exc)
                await handle_failed(self, exc)
                return
            await handle_stop(self)

    def stop_requested(self) -> bool:
        """Whether this service was asked to stop: process shutdown, or its own shutdown if it is optional.

        An optional service can be stopped on its own (its app reloading). A required one is always a child
        of ``Hassette`` (``_validate_parent``), and the root sets the process event before any child's own,
        so only process shutdown stops it; stopped any other way, it ends as a reported failure (spec 134 D8).
        """
        return self.hassette.shutdown_event.is_set() or (not self.required and self.shutdown_event.is_set())

    def is_running(self) -> bool:
        """Return True while the ``serve()`` task exists and has not finished."""
        return self._serve_task is not None and not self._serve_task.done()
