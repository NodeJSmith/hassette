import asyncio
import typing
import uuid
from contextlib import suppress
from logging import INFO, Filter, Logger, LogRecord, getLogger
from typing import Any, ClassVar, TypeVar, final

from hassette.exceptions import CannotOverrideFinalError
from hassette.resources.lifecycle import (
    CLEANUP_SECONDS,
    TASK_CANCEL_SECONDS,
    cancel,
    children_budget_remaining,
    coordinate_initialize,
    coordinate_shutdown,
    create_service_status_event,
    elapsed_since,
    handle_failed,
    handle_running,
    handle_starting,
    handle_stop,
    mark_not_ready,
)
from hassette.resources.operations import (
    finalize_shutdown_report,
    ordered_children_for_shutdown,
    run_hooks,
    shutdown_batch,
)
from hassette.resources.teardown import (
    TeardownCause,
    TeardownReport,
    merge_teardown_reports,
)
from hassette.types.enums import ResourceRole, ResourceStatus
from hassette.types.types import FRAMEWORK_APP_KEY_PREFIX, LOG_LEVEL_TYPE, SourceTier

from .mixins import LifecycleMixin

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import Hassette, TaskBucket

_ResourceT = TypeVar("_ResourceT", bound="Resource")


class FinalMeta(type):
    """Disallow overriding methods marked @final in any ancestor."""

    LOADED_CLASSES: ClassVar[set[str]] = set()

    def __init__(cls, name, bases, ns, **kw):
        super().__init__(name, bases, ns, **kw)
        subclass_name = f"{cls.__module__}.{cls.__qualname__}"
        if subclass_name in FinalMeta.LOADED_CLASSES:
            return

        FinalMeta.LOADED_CLASSES.add(subclass_name)

        # Collect all methods marked as final from the MRO (excluding object and cls itself)
        finals: dict[str, type] = {}
        for ancestor in cls.__mro__[1:]:
            if ancestor is object:
                continue
            for attr, obj in ancestor.__dict__.items():
                if getattr(obj, "__final__", False):
                    finals.setdefault(attr, ancestor)

        for method_name, origin in finals.items():
            if method_name in ns:
                new_obj = ns[method_name]
                old_obj = origin.__dict__.get(method_name)
                if new_obj is old_obj:
                    continue

                origin_name = f"{origin.__qualname__}"
                subclass_name = f"{cls.__module__}.{cls.__qualname__}"
                suggested_alt = f"on_{method_name}" if not method_name.startswith("on_") else method_name

                loc = None
                code = getattr(new_obj, "__code__", None)
                if code is not None:
                    loc = f"{code.co_filename}:{code.co_firstlineno}"

                raise CannotOverrideFinalError(method_name, origin_name, subclass_name, suggested_alt, loc)


class _ResourceContextFilter(Filter):
    """Stamps source_tier on every LogRecord so downstream handlers and structlog processors can read it."""

    def __init__(self, source_tier: str) -> None:
        super().__init__()
        self.source_tier = source_tier

    def filter(self, record: LogRecord) -> bool:
        record.source_tier = self.source_tier  # pyright: ignore[reportAttributeAccessIssue]
        return True


class Resource(LifecycleMixin, metaclass=FinalMeta):
    """Base class for resources in the Hassette framework."""

    _unique_name: str
    """Unique name for the instance."""

    role: ClassVar[ResourceRole] = ResourceRole.RESOURCE
    """Role of the resource, e.g. 'App', 'Service', etc."""

    depends_on: ClassVar[list[type["Resource"]]] = []
    """Resource types that must be ready before this resource initializes."""

    source_tier: ClassVar[SourceTier] = "framework"
    """Telemetry classification inherited by Bus/Scheduler children for DB registration.

    Defaults to ``'framework'`` for all Resources. User-facing app classes (``App``,
    ``AppSync``) override to ``'app'``. Do not set ``source_tier = 'app'`` on framework
    components — their Bus/Scheduler children inherit this value and it determines
    cleanup, reconciliation, and UI display behavior.
    """

    index: int = 0
    """Instance index. Apps override with their manifest-assigned index."""

    task_bucket: "TaskBucket"
    """Task bucket for managing tasks owned by this instance."""

    is_task_bucket: ClassVar[bool] = False
    """True on TaskBucket (and any subclass that keeps it True, since it is inherited); used in
    __init__ so a Resource that is its own task bucket skips the factory, avoiding a circular import."""

    _default_task_bucket_factory: ClassVar["Callable[[Hassette, Resource], TaskBucket] | None"] = None
    """Factory registered by hassette.task_bucket at import time; raises if unset."""

    parent: "Resource | None" = None
    """Reference to the parent resource, if any."""

    children: list["Resource"]
    """List of child resources."""

    logger: Logger
    """Logger for the instance."""

    unique_id: str
    """Unique identifier for the instance."""

    class_name: typing.ClassVar[str]
    """Name of the class, set on subclassing."""

    hassette: "Hassette"
    """Reference to the Hassette instance."""

    def __init_subclass__(cls) -> None:
        cls.class_name = cls.__name__
        if "depends_on" not in cls.__dict__:
            cls.depends_on = list(cls.depends_on)

    def __init__(
        self, hassette: "Hassette", task_bucket: "TaskBucket | None" = None, parent: "Resource | None" = None
    ) -> None:
        super().__init__()

        self.unique_id = uuid.uuid4().hex[:8]

        self.hassette = hassette
        self.parent = parent
        self.children = []

        self._setup_logger()

        if self.is_task_bucket:
            # TaskBucket is special: it is its own task bucket. pyright can't narrow `self` to
            # TaskBucket through the `is_task_bucket: ClassVar[bool]` guard, so the assignment of
            # `self` to the TaskBucket-typed attribute needs the suppression.
            self.task_bucket = self  # pyright: ignore[reportAttributeAccessIssue]
        else:
            if task_bucket is not None:
                self.task_bucket = task_bucket
            else:
                factory = Resource._default_task_bucket_factory
                if factory is None:
                    raise RuntimeError(
                        f"Cannot construct {type(self).__name__}: no TaskBucket factory is registered. "
                        "Ensure hassette.task_bucket is imported before constructing any Resource."
                    )
                self.task_bucket = factory(self.hassette, self)

    def _get_logger_name(self) -> str:
        if self.class_name == "Hassette":
            return "hassette"

        logger_name = (
            self.unique_name[len("Hassette.") :] if self.unique_name.startswith("Hassette.") else self.unique_name
        )

        return f"hassette.{logger_name}"

    def _setup_logger(self) -> None:
        self.logger = getLogger(self._get_logger_name())

        try:
            self.logger.setLevel(self.config_log_level)
        except (ValueError, TypeError) as exc:
            self.logger.error(
                "Invalid log level %r for %s; falling back to INFO: %s",
                self.config_log_level,
                self.unique_name,
                exc,
            )
            self.logger.setLevel(INFO)

        self.logger.addFilter(_ResourceContextFilter(self.source_tier))

    def __repr__(self) -> str:
        return f"<{type(self).__name__} unique_name={self.unique_name}>"

    @property
    def unique_name(self) -> str:
        """Get the unique name of the instance."""
        if not hasattr(self, "_unique_name") or not self._unique_name:
            if self.parent:
                self._unique_name = f"{self.parent.unique_name}.{self.class_name}"
            else:
                self._unique_name = f"{self.class_name}.{self.unique_id}"

        return self._unique_name

    @property
    def app_key(self) -> str:
        """Identity key for telemetry. App overrides with its manifest key."""
        return f"{FRAMEWORK_APP_KEY_PREFIX}{self.class_name}"

    @property
    def instance_name(self) -> str | None:
        """Owning app instance's name for telemetry, or None for framework resources.

        Resolved from the resource's ``app_config`` when present (App subclasses);
        plain framework resources have no app config and return None.
        """
        return getattr(getattr(self, "app_config", None), "instance_name", None)

    @property
    def owner_id(self) -> str:
        # nearest App's unique_name, else Hassette's unique_name
        if self.parent:
            return self.parent.unique_name
        return self.unique_name

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource.

        Subclasses that map to a per-service ``LoggingConfig`` field override this with a
        one-line property returning that field. That repetition is deliberate and stays:
        the alternative — a class attribute naming the field, read here via ``getattr`` —
        trades a checked attribute access for a string, and the pattern spans 30 files,
        three of which are generated sync facades. ``tools/check_duplicate_code.py`` reports
        the overrides as clones because its matched region also swallows the unrelated
        statement above each one, so they cannot be annotated with ``dup-ignore`` markers
        without mislabeling that statement (see #1570).
        """
        return self.hassette.config.logging.log_level

    def add_child(self, child_class: type[_ResourceT], **kwargs: Any) -> _ResourceT:
        """Create and add a child resource to this resource.

        Args:
            child_class: The class of the child resource to create.
            **kwargs: Keyword arguments to pass to the child resource's constructor.

        Returns:
            The created child resource.
        """
        if "parent" in kwargs:
            raise ValueError("Cannot specify 'parent' argument when adding a child resource; it is set automatically.")

        inst = child_class(hassette=self.hassette, parent=self, **kwargs)
        self.children.append(inst)
        return inst

    async def _auto_wait_dependencies(self) -> None:
        """Wait for all declared depends_on types to become ready before lifecycle hooks fire.

        Early-returns when:
        - ``depends_on`` is empty (no declared deps)
        - ``hassette._skip_dependency_check`` is True (test harness bypass)

        Raises:
            RuntimeError: If no matching child is found for a declared dep type, or if
                ``hassette.wait_for_ready`` returns False without a concurrent shutdown signal.

        On shutdown during wait, calls ``mark_not_ready()`` and returns without raising.
        """
        if not self.depends_on:
            return
        if self.hassette._should_skip_dependency_check():
            return

        # App-level depends_on is not yet supported (#581).
        if self.role == ResourceRole.APP:
            raise RuntimeError(
                f"{self.class_name} declares depends_on but App-level depends_on "
                f"is not yet supported. See https://github.com/NodeJSmith/hassette/issues/581"
            )

        # Deduplicates by instance identity (id), not by type — necessary because
        # a single child instance may satisfy multiple dep_type entries (e.g.,
        # depends_on = [Service, DatabaseService] where DatabaseService matches both).
        seen: set[int] = set()
        deps: list[Resource] = []
        for dep_type in self.depends_on:
            matches = [child for child in self.hassette.children if isinstance(child, dep_type)]
            if not matches:
                raise RuntimeError(
                    f"{self.class_name} declares depends_on=[{dep_type.__name__}] "
                    f"but no matching child found in Hassette"
                )
            for match in matches:
                if id(match) not in seen:
                    seen.add(id(match))
                    deps.append(match)

        dep_names = ", ".join(dep.class_name for dep in deps)
        self.logger.info("Waiting for dependencies: [%s]", dep_names)

        ready = await self.hassette.wait_for_ready(deps)
        if not ready:
            if self.hassette.shutdown_event.is_set():
                mark_not_ready(self, "shutdown during dependency wait")
                return
            status_report = ", ".join(f"{dep.class_name}({dep.status.value})" for dep in deps)
            raise RuntimeError(f"{self.class_name} timed out waiting for dependencies: {status_report}")

        self.logger.debug("Dependencies satisfied: [%s]", dep_names)

    def _force_terminal(self) -> None:
        """Recursively force this resource and all descendants to STOPPED terminal state.

        Cancels tasks for resources that were never given a shutdown signal (grandchildren).
        Service overrides this to also cancel _serve_task.

        Records ``TeardownCause.FORCED_TERMINAL`` on the resource's teardown report before
        cancelling any work, so restart is refused even if a caller inspects the report before
        this method's cancellation and terminal-status side effects finish. Leaves an already
        completed report unchanged — a resource that already proved ``is_restart_safe`` (or
        already recorded other unsafe evidence) is not retroactively altered.

        Note: this does NOT call on_shutdown() hooks, so bus subscriptions and scheduler
        jobs owned by force-terminated resources are not cleaned up. This is intentional —
        calling hooks risks re-entrancy with the child's own finally block. Stale
        subscriptions may remain active against STOPPED resources; this is an accepted
        gap because force-terminal is nearly always followed by process exit.

        Seals the TaskBucket and takes its synchronous pending-name snapshot before recording
        the report, so a whole-body-deadline force-terminal call (triggered by the shutdown
        coordinator in ``lifecycle.py`` when ``_shutdown_body()`` itself never reaches its own
        TaskBucket stage -- see ``_run_task_bucket_shutdown_stage()``) still records TaskBucket's
        final pending names even though the interrupted body's own stage never returned.

        The "leave an already-completed report unchanged" guard below only skips re-recording
        that report -- it does NOT skip the recursion into children. A resource whose own report
        was already stored (e.g. a clean teardown, or an earlier force-terminal call) can still
        have unresponsive descendants of its own; ``Hassette._shutdown_body()`` calls
        ``child._force_terminal()`` unconditionally on the total-timeout path specifically to
        reach those descendants, so returning early here would leave a hung grandchild's tasks
        alive after shutdown has already declared the tree terminal.
        """
        if self._teardown_report is None:
            self.task_bucket.seal()
            pending = self.task_bucket.pending_task_names()
            causes: list[TeardownCause] = [TeardownCause.FORCED_TERMINAL]
            if pending:
                causes.append(TeardownCause.TASKS_PENDING)
            self._teardown_report = TeardownReport(causes=tuple(causes), pending_tasks=pending)
        cancel(self)
        # Cancel an active shutdown coordinator too -- but never the currently running task
        # (self-cancellation mid-synchronous-execution is a footgun and would not take effect
        # until the next suspension point anyway). This is the cross-resource case: a parent's
        # own shutdown body force-terminating an unresponsive child whose shutdown coordinator
        # is still pending elsewhere. Because the report above is stored first, the child's
        # coordinator (`_run_shutdown_coordinator`) treats the resulting cancellation as a
        # restart-unsafe return rather than letting `CancelledError` reach its joined callers.
        current_task = asyncio.current_task()
        if (
            self._shutdown_task is not None
            and not self._shutdown_task.done()
            and self._shutdown_task is not current_task
        ):
            self._shutdown_task.cancel()
        self.task_bucket.cancel_all_sync()
        self._status = ResourceStatus.STOPPED  # bypass setter to skip validation
        mark_not_ready(self, "shutdown timed out")
        for child in self.children:
            child._force_terminal()

    async def _shutdown_children(self) -> TeardownReport:
        """Propagate shutdown to children and aggregate their teardown reports.

        Children shut down concurrently, in reverse insertion order
        (``ordered_children_for_shutdown()``), as a single ``shutdown_batch()`` call — see that
        function for the per-child classification rules (failed/restart-unsafe/timed-out).

        Children benefit from any slack the hooks pool didn't use — their budget is
        ``max(children_floor_seconds, body_deadline - now)``, so early-finishing hooks pass
        their slack to children naturally.
        """
        timeout = children_budget_remaining(self)
        self.logger.debug(
            "%s: entering _shutdown_children() with %.2fs budgeted",
            self.unique_name,
            timeout,
        )
        children = ordered_children_for_shutdown(self)
        if not children:
            return TeardownReport()

        result = await shutdown_batch(self, children, timeout)
        return finalize_shutdown_report(result.reports, result.causes, result.affected)

    async def _run_task_bucket_shutdown_stage(self) -> TeardownReport:
        """Seal the TaskBucket, cancel tracked work, and record final pending-task evidence.

        First-class shutdown stage: sealing, cancellation, and the final synchronous pending-name
        snapshot all happen here, before subclass ``cleanup()`` runs (design: "Sealing,
        cancellation, and final TaskBucket inspection form a first-class shutdown stage before
        subclass cleanup"). Kept separate from ``cleanup()`` so an enclosing whole-body timeout or
        force-terminal call can still inspect the sealed bucket directly (see
        ``_force_terminal()``) even if this stage itself is interrupted before returning.

        Uses the pre-computed ``task_cancel_seconds`` from the ``ShutdownBudget`` — a fixed
        allocation from the total, not a fraction of whatever happens to remain.
        """
        self.task_bucket.seal()
        budget = self._shutdown_budget
        cancel_budget = budget.task_cancel_seconds if budget is not None else TASK_CANCEL_SECONDS
        self.logger.debug(
            "%s: entering task-bucket cancel with %.2fs budgeted",
            self.unique_name,
            cancel_budget,
        )
        cancel_start = asyncio.get_running_loop().time()
        await self.task_bucket.cancel_all(timeout=cancel_budget)
        self.logger.debug(
            "%s: task-bucket cancel stage completed in %.2fs",
            self.unique_name,
            elapsed_since(cancel_start),
        )
        pending = self.task_bucket.pending_task_names()
        if pending:
            return TeardownReport(causes=(TeardownCause.TASKS_PENDING,), pending_tasks=pending)
        return TeardownReport()

    async def _run_post_hook_shutdown_stage(self) -> TeardownReport:
        """Cleanup, child propagation, and terminal event emission shared by every
        ``_shutdown_body()`` implementation (Resource, Service, and Hassette).

        Runs after the class-specific shutdown hooks have already executed. Returns evidence
        instead of setting flags directly — the shutdown coordinator (``coordinate_shutdown()``
        in ``hassette.resources.lifecycle``) is the sole owner of the final stored
        ``TeardownReport``.
        """
        reports: list[TeardownReport] = [await self._run_task_bucket_shutdown_stage()]

        budget = self._shutdown_budget
        cleanup_timeout = budget.cleanup_seconds if budget is not None else CLEANUP_SECONDS
        self.logger.debug(
            "%s: entering cleanup() with %.2fs budgeted",
            self.unique_name,
            cleanup_timeout,
        )
        cleanup_start = asyncio.get_running_loop().time()
        try:
            async with asyncio.timeout(cleanup_timeout):
                await self.cleanup()
        except TimeoutError:
            self.logger.warning("cleanup() timed out after %ss for %s", cleanup_timeout, self.unique_name)
            reports.append(TeardownReport(causes=(TeardownCause.CLEANUP_TIMED_OUT,), failed_operations=("cleanup",)))
        except Exception as exc:
            self.logger.exception("Error during cleanup: %s %s", type(exc).__name__, exc)
            reports.append(TeardownReport(causes=(TeardownCause.CLEANUP_FAILED,), failed_operations=("cleanup",)))
        self.logger.debug(
            "%s: cleanup() stage completed in %.2fs",
            self.unique_name,
            elapsed_since(cleanup_start),
        )

        children_start = asyncio.get_running_loop().time()
        children_report = await self._shutdown_children()
        self.logger.debug(
            "%s: child shutdown propagation completed in %.2fs",
            self.unique_name,
            elapsed_since(children_start),
        )
        reports.append(children_report)

        if children_report.is_restart_safe:
            await self._on_children_stopped()

        if not self.hassette.event_streams_closed:
            try:
                await handle_stop(self)
            except Exception as exc:
                self.logger.exception("Error during stopping %s %s", type(exc).__name__, exc)
        else:
            self.logger.debug("Skipping STOPPED event as event streams are closed")

        return merge_teardown_reports(*reports)

    async def _on_children_stopped(self) -> None:
        """Called after children shut down cleanly, before this resource's STOPPED event.

        Only runs on the success path — skipped when child propagation times out
        (the timeout handler force-patches children and the caller handles fallback
        teardown, e.g., Hassette's finally block calls close_streams()).

        Override to run logic that must happen after children are shut down but
        before the parent emits its own STOPPED event. Default is a no-op.
        Overrides MUST call ``await super()._on_children_stopped()``.

        Note: _shutdown_body() is intentionally not @final — this hook exists so
        subclasses do NOT need to override _shutdown_body() for post-children behavior.
        """

    @final
    async def initialize(self) -> None:
        """Coordinator front door: joins or creates the resource's one owned initialization
        attempt.

        This method itself never runs class-specific initialization work — see
        ``_initialize_body()``, which every initialization attempt (direct calls, ``start()``'s
        spawned joiner, and ``restart()``) ultimately runs exactly once per attempt. See
        ``coordinate_initialize()`` in ``hassette.resources.lifecycle`` for the full admission
        sequence (re-entry rejection, joining an active shutdown, restart refusal, task
        ownership).
        """
        await coordinate_initialize(self)

    async def _initialize_body(self) -> None:
        """Class-specific initialization work, run exactly once per coordinated attempt.

        NOTE: keep child propagation in sync with Service._initialize_body().
        NOTE: _auto_wait_dependencies() runs before hooks — keep in sync with Service.
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
        await run_hooks(self, [self.before_initialize, self.on_initialize, self.after_initialize])
        for child in self.children:
            if child.status not in (ResourceStatus.STARTING, ResourceStatus.RUNNING):
                await child.initialize()
        await handle_running(self)

    async def before_initialize(self) -> None:
        """Optional: prepare to accept new work, allocate sockets, queues, temp files, etc."""
        pass

    async def on_initialize(self) -> None:
        """Primary hook: perform your own initialization (sockets, queues, temp files…)."""
        pass

    async def after_initialize(self) -> None:
        """Optional: finalize initialization, signal readiness, etc."""
        pass

    @final
    async def shutdown(self) -> TeardownReport:
        """Coordinator front door: joins or creates the resource's one owned shutdown attempt
        and returns its stored ``TeardownReport``.

        This method itself never runs class-specific shutdown work — see ``_shutdown_body()``,
        which the coordinator runs exactly once per attempt. Repeated calls after completion
        return the same stored report without rerunning hooks. See ``coordinate_shutdown()`` in
        ``hassette.resources.lifecycle`` for the full sequence (re-entry rejection, initializer
        cancellation/observation, bounded body observation, force-terminal evidence merging).
        """
        return await coordinate_shutdown(self)

    async def _shutdown_body(self) -> TeardownReport:
        """Class-specific shutdown work, run exactly once per coordinated attempt.

        NOTE: keep hook ordering in sync with Service._shutdown_body().
        """
        hook_errors = await run_hooks(
            self,
            [self.before_shutdown, self.on_shutdown, self.after_shutdown],
            continue_on_error=True,
            bound_to_shutdown_budget=True,
        )
        hook_report = (
            TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_FAILED,), failed_operations=("shutdown_hooks",))
            if hook_errors
            else TeardownReport()
        )
        tail_report = await self._run_post_hook_shutdown_stage()
        return merge_teardown_reports(hook_report, tail_report)

    async def before_shutdown(self) -> None:
        """Optional: stop accepting new work, signal loops to wind down, etc."""
        pass

    async def on_shutdown(self) -> None:
        """Primary hook: release your own stuff (sockets, queues, temp files…)."""
        pass

    async def after_shutdown(self) -> None:
        """Optional: last-chance actions after on_shutdown, before cleanup/STOPPED."""
        pass

    async def _emit_readiness_event(self) -> None:
        """Emit a service_status event reflecting the current readiness state.

        Call this from an async context (e.g., inside ``serve()``) after calling
        ``mark_ready()`` or ``mark_not_ready()`` to propagate mid-operation
        readiness changes to the frontend.

        This method is intended for mid-operation readiness changes while the service
        status is RUNNING. Do not call after handle_failed(), handle_stop(), or
        handle_crash() — those lifecycle methods emit their own status events including
        the current readiness state. Calling this method after a lifecycle transition
        will emit a duplicate event.

        Exceptions are caught internally and logged as warnings — callers do not need
        to wrap with ``suppress(Exception)``.
        """
        try:
            event = create_service_status_event(
                self, self._status, ready=self.is_ready(), ready_phase=self._ready_reason
            )
            await self.hassette.send_event(event)
        except Exception:
            self.logger.warning(
                "%s failed to emit readiness event (ready=%s, phase=%s)",
                self.unique_name,
                self.is_ready(),
                self._ready_reason,
                exc_info=True,
            )

    async def cleanup(self, timeout: float | None = None) -> None:
        """Cleanup resources owned by the instance.

        Called during shutdown, after ``_run_task_bucket_shutdown_stage()`` has already sealed
        and cancelled the TaskBucket's tracked work as its own first-class stage -- this method
        no longer owns TaskBucket cancellation. Subclass overrides use this for resources they
        own directly (caches, connections, etc.); the base implementation only cancels and
        observes the resource's own initialization task, if one is still pending.
        """
        timeout = timeout or self.hassette.config.lifecycle.resource_shutdown_timeout_seconds

        cancel(self)
        if self._init_task and not self._init_task.done():
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(self._init_task, timeout=timeout)

        self.logger.debug("Cleaned up resources")
