import asyncio
import typing
import uuid
from contextlib import suppress
from logging import INFO, Filter, Logger, LogRecord, getLogger
from typing import Any, ClassVar, TypeVar, final

from hassette.exceptions import CannotOverrideFinalError
from hassette.resources.lifecycle import (
    cancel,
    create_service_status_event,
    handle_failed,
    handle_running,
    handle_starting,
    handle_stop,
    mark_not_ready,
    request_shutdown,
)
from hassette.resources.operations import ordered_children_for_shutdown, run_hooks
from hassette.types.enums import TERMINAL_STATUSES, ResourceRole, ResourceStatus
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

        if subclass_name in ("hassette.resources.service.Service", "hassette.core.core.Hassette"):
            # allow Service to override Resource's final initialize/shutdown
            # allow Hassette to override Resource's final shutdown (total timeout wrapper)
            return

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

    shutting_down: bool = False
    """Flag indicating whether the instance is in the process of shutting down."""

    initializing: bool = False
    """Flag indicating whether the instance is in the process of starting up."""

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
        """Return the log level from the config for this resource."""
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

        Note: this does NOT call on_shutdown() hooks, so bus subscriptions and scheduler
        jobs owned by force-terminated resources are not cleaned up. This is intentional —
        calling hooks risks re-entrancy with the child's own finally block. Stale
        subscriptions may remain active against STOPPED resources; this is an accepted
        gap because force-terminal is nearly always followed by process exit.
        """
        if self.shutdown_completed:
            return
        cancel(self)
        self.task_bucket.cancel_all_sync()
        self.shutting_down = False
        self.shutdown_completed = True
        self._status = ResourceStatus.STOPPED  # bypass setter to skip validation
        mark_not_ready(self, "shutdown timed out")
        for child in self.children:
            child._force_terminal()

    async def _shutdown_children(self) -> bool:
        """Propagate shutdown to children. Returns True if all completed within timeout and without errors."""
        timeout = self.hassette.config.lifecycle.resource_shutdown_timeout_seconds
        children = ordered_children_for_shutdown(self)
        if not children:
            return True
        try:
            async with asyncio.timeout(timeout):
                all_clean = True
                results = await asyncio.gather(
                    *[child.shutdown() for child in children],
                    return_exceptions=True,
                )
                for child, result in zip(children, results, strict=True):
                    if isinstance(result, Exception):
                        all_clean = False
                        self.logger.error("Child %s shutdown failed: %s", child.unique_name, result)
            return all_clean
        except TimeoutError:
            self.logger.error("Timed out waiting for children to shut down after %ss", timeout)
            for child in children:
                child._force_terminal()
            return False

    async def _finalize_shutdown(self) -> None:
        """Common shutdown cleanup: cancel tasks, propagate to children, emit stopped event."""
        timeout = self.hassette.config.lifecycle.resource_shutdown_timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                await self.cleanup()
        except TimeoutError:
            self.logger.warning("cleanup() timed out after %ss for %s", timeout, self.unique_name)
        except Exception as exc:
            self.logger.exception("Error during cleanup: %s %s", type(exc).__name__, exc)

        children_clean = await self._shutdown_children()

        self.shutdown_completed = True

        if self.initializing:
            if self.shutdown_event.is_set():
                self.logger.debug(
                    "%s shutting down with initializing=True (shutdown requested during init)", self.unique_name
                )
            else:
                self.logger.warning("%s shutting down with initializing=True — this indicates a bug", self.unique_name)
            self.initializing = False

        if children_clean:
            await self._on_children_stopped()

        if not self.hassette.event_streams_closed:
            try:
                await handle_stop(self)
            except Exception as exc:
                self.logger.exception("Error during stopping %s %s", type(exc).__name__, exc)
        else:
            self.logger.debug("Skipping STOPPED event as event streams are closed")

    async def _on_children_stopped(self) -> None:
        """Called after children shut down cleanly, before this resource's STOPPED event.

        Only runs on the success path — skipped when child propagation times out
        (the timeout handler force-patches children and the caller handles fallback
        teardown, e.g., Hassette's finally block calls close_streams()).

        Override to run logic that must happen after children are shut down but
        before the parent emits its own STOPPED event. Default is a no-op.
        Overrides MUST call ``await super()._on_children_stopped()``.

        Note: _finalize_shutdown() is intentionally not @final — this hook exists
        so subclasses do NOT need to override _finalize_shutdown() for post-children
        behavior.
        """

    @final
    async def initialize(self) -> None:
        """Initialize the instance by calling the lifecycle hooks in order.

        NOTE: keep flag resets and child propagation in sync with Service.initialize().
        NOTE: _auto_wait_dependencies() runs before hooks — keep in sync with Service.initialize().
        """
        self.shutdown_completed = False
        self.shutdown_event.clear()

        if self.initializing:
            return
        self.initializing = True

        self.logger.debug("Initializing %s: %s", self.role, self.unique_name)
        await handle_starting(self)

        try:
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
        finally:
            self.initializing = False

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
    async def shutdown(self) -> None:
        """Shutdown the instance by calling the lifecycle hooks in order.

        NOTE: keep guards and flag resets in sync with Service.shutdown().
        """
        if self.shutdown_completed:
            return
        if self.shutting_down:
            return
        self.shutting_down = True
        if self._status not in TERMINAL_STATUSES:
            self.status = ResourceStatus.STOPPING
        request_shutdown(self, f"{self.unique_name} shutdown")

        try:
            await run_hooks(
                self,
                [self.before_shutdown, self.on_shutdown, self.after_shutdown],
                continue_on_error=True,
            )
        finally:
            await self._finalize_shutdown()
            self.shutting_down = False

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

        This method is called during shutdown to ensure that all resources are properly released.
        """
        timeout = timeout or self.hassette.config.lifecycle.resource_shutdown_timeout_seconds

        cancel(self)
        with suppress(asyncio.CancelledError):
            if self._init_task:
                await asyncio.wait_for(self._init_task, timeout=timeout)

        await self.task_bucket.cancel_all()
        self.logger.debug("Cleaned up resources")
