import asyncio
import typing
import uuid
from abc import abstractmethod
from collections.abc import Coroutine
from contextlib import suppress
from functools import cached_property
from logging import INFO, Logger, getLogger
from typing import Any, ClassVar, TypeVar, final

from diskcache import Cache

from hassette.exceptions import CannotOverrideFinalError, FatalError
from hassette.types.enums import ResourceRole, ResourceStatus

from .mixins import LifecycleMixin

if typing.TYPE_CHECKING:
    from hassette import Hassette, TaskBucket

T = TypeVar("T")
CoroLikeT = Coroutine[Any, Any, T]

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

        if subclass_name in ("hassette.resources.base.Service", "hassette.core.core.Hassette"):
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


class Resource(LifecycleMixin, metaclass=FinalMeta):
    """Base class for resources in the Hassette framework."""

    _shutting_down: bool = False
    """Flag indicating whether the instance is in the process of shutting down."""

    _initializing: bool = False
    """Flag indicating whether the instance is in the process of starting up."""

    _unique_name: str
    """Unique name for the instance."""

    _cache: Cache | None
    """Private attribute to hold the cache, to allow lazy initialization."""

    role: ClassVar[ResourceRole] = ResourceRole.RESOURCE
    """Role of the resource, e.g. 'App', 'Service', etc."""

    task_bucket: "TaskBucket"
    """Task bucket for managing tasks owned by this instance."""

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

    def __init__(
        self, hassette: "Hassette", task_bucket: "TaskBucket | None" = None, parent: "Resource | None" = None
    ) -> None:
        from hassette.task_bucket import TaskBucket

        super().__init__()

        self._cache = None  # lazy init
        self.unique_id = uuid.uuid4().hex[:8]

        self.hassette = hassette
        self.parent = parent
        self.children = []

        self._setup_logger()

        if type(self) is TaskBucket:
            # TaskBucket is special: it is its own task bucket
            self.task_bucket = self
        else:
            self.task_bucket = task_bucket or TaskBucket(self.hassette, parent=self)

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
        except (ValueError, TypeError) as e:
            self.logger.error(
                "Invalid log level %r for %s; falling back to INFO: %s",
                self.config_log_level,
                self.unique_name,
                e,
            )
            self.logger.setLevel(INFO)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} unique_name={self.unique_name}>"

    @cached_property
    def cache(self) -> Cache:
        """Disk cache for storing arbitrary data. All instances of the same resource class share a cache directory."""
        if self._cache is not None:
            return self._cache

        # set up cache
        cache_dir = self.hassette.config.data_dir.joinpath(self.class_name).joinpath("cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = Cache(cache_dir, size_limit=self.hassette.config.default_cache_size)
        return self._cache

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
    def owner_id(self) -> str:
        # nearest App's unique_name, else Hassette's unique_name
        if self.parent:
            return self.parent.unique_name
        return self.unique_name

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.log_level

    def add_child(self, child_class: type[_ResourceT], **kwargs) -> _ResourceT:
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

    async def _run_hooks(
        self, hooks: list[typing.Callable[[], typing.Awaitable[None]]], *, continue_on_error: bool = False
    ) -> None:
        """Execute lifecycle hooks with error handling.

        Args:
            hooks: List of async callables to execute in order.
            continue_on_error: If False (initialize), re-raise on Exception.
                If True (shutdown), log and continue to next hook.
        """
        for method in hooks:
            try:
                await method()
            except asyncio.CancelledError:
                if continue_on_error:
                    self.logger.warning("Shutdown hook was cancelled, forcing cleanup")
                with suppress(Exception):
                    await self.handle_failed(asyncio.CancelledError())
                raise
            except Exception as e:
                if continue_on_error:
                    self.logger.error("Error during shutdown: %s %s", type(e).__name__, e)
                    with suppress(Exception):
                        await self.handle_failed(e)
                else:
                    with suppress(Exception):
                        await self.handle_failed(e)
                    raise

    def _ordered_children_for_shutdown(self) -> list["Resource"]:
        """Return children in shutdown order (reverse insertion)."""
        return list(reversed(self.children))

    def _force_terminal(self) -> None:
        """Recursively force this resource and all descendants to STOPPED terminal state.

        Cancels tasks for resources that were never given a shutdown signal (grandchildren).
        Service overrides this to also cancel _serve_task.

        Note: this does NOT call on_shutdown() hooks, so bus subscriptions and scheduler
        jobs owned by force-terminated resources are not cleaned up. This is intentional —
        calling hooks risks re-entrancy with the child's own finally block. In practice,
        force-terminal only fires on timeout paths where process exit is imminent.
        """
        if self._shutdown_completed:
            return
        self.cancel()
        self.task_bucket.cancel_all_sync()
        self._shutting_down = False
        self._shutdown_completed = True
        self.status = ResourceStatus.STOPPED
        self.mark_not_ready("shutdown timed out")
        for child in self.children:
            child._force_terminal()

    async def _finalize_shutdown(self) -> None:
        """Common shutdown cleanup: cancel tasks, propagate to children, emit stopped event."""
        timeout = self.hassette.config.resource_shutdown_timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                await self.cleanup()
        except TimeoutError:
            self.logger.warning("cleanup() timed out after %ss for %s", timeout, self.unique_name)
        except Exception as e:
            self.logger.exception("Error during cleanup: %s %s", type(e).__name__, e)

        # Propagate shutdown to children — submitted in reverse insertion order,
        # but executed concurrently via gather (completion order is not guaranteed).
        children = self._ordered_children_for_shutdown()
        children_timed_out = False
        if children:
            try:
                async with asyncio.timeout(timeout):
                    results = await asyncio.gather(
                        *[child.shutdown() for child in children],
                        return_exceptions=True,
                    )
                    for child, result in zip(children, results, strict=True):
                        if isinstance(result, Exception):
                            self.logger.error("Child %s shutdown failed: %s", child.unique_name, result)
            except TimeoutError:
                children_timed_out = True
                self.logger.error("Timed out waiting for children to shut down after %ss", timeout)
                for child in children:
                    child._force_terminal()

        self._shutdown_completed = True

        if self._initializing:
            if self.shutdown_event.is_set():
                self.logger.debug(
                    "%s shutting down with _initializing=True (shutdown requested during init)", self.unique_name
                )
            else:
                self.logger.warning("%s shutting down with _initializing=True — this indicates a bug", self.unique_name)
            self._initializing = False

        # Hook runs only on clean shutdown — not after timeout, where children
        # are force-patched and may still have running tasks.
        if not children_timed_out:
            await self._on_children_stopped()

        if not self.hassette.event_streams_closed:
            try:
                await self.handle_stop()
            except Exception as e:
                self.logger.exception("Error during stopping %s %s", type(e).__name__, e)
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
        """
        self._shutdown_completed = False
        self.shutdown_event.clear()

        if self._initializing:
            return
        self._initializing = True

        self.logger.debug("Initializing %s: %s", self.role, self.unique_name)
        await self.handle_starting()

        try:
            await self._run_hooks([self.before_initialize, self.on_initialize, self.after_initialize])
            for child in self.children:
                if child.status not in (ResourceStatus.STARTING, ResourceStatus.RUNNING):
                    await child.initialize()
            await self.handle_running()
        finally:
            self._initializing = False

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
        if self._shutdown_completed:
            return
        if self._shutting_down:
            return
        self._shutting_down = True
        self.request_shutdown("shutdown")
        self.logger.debug("Shutting down %s: %s", self.role, self.unique_name)

        try:
            await self._run_hooks(
                [self.before_shutdown, self.on_shutdown, self.after_shutdown],
                continue_on_error=True,
            )
        finally:
            await self._finalize_shutdown()
            self._shutting_down = False

    async def before_shutdown(self) -> None:
        """Optional: stop accepting new work, signal loops to wind down, etc."""
        pass

    async def on_shutdown(self) -> None:
        """Primary hook: release your own stuff (sockets, queues, temp files…)."""
        pass

    async def after_shutdown(self) -> None:
        """Optional: last-chance actions after on_shutdown, before cleanup/STOPPED."""
        pass

    async def restart(self) -> None:
        """Restart the instance by shutting it down and re-initializing it."""
        self.logger.debug("Restarting '%s' %s", self.class_name, self.role)
        await self.shutdown()
        await self.initialize()

    async def cleanup(self, timeout: int | None = None) -> None:
        """Cleanup resources owned by the instance.

        This method is called during shutdown to ensure that all resources are properly released.
        """
        timeout = timeout or self.hassette.config.resource_shutdown_timeout_seconds

        self.cancel()
        with suppress(asyncio.CancelledError):
            if self._init_task:
                await asyncio.wait_for(self._init_task, timeout=timeout)

        await self.task_bucket.cancel_all()
        self.logger.debug("Cleaned up resources")

        if self._cache is not None:
            try:
                self.cache.close()
            except Exception as e:
                self.logger.exception("Error closing cache: %s %s", type(e).__name__, e)


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
    """

    role: ClassVar[ResourceRole] = ResourceRole.SERVICE

    _serve_task: asyncio.Task | None = None

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
        """
        self._shutdown_completed = False
        self.shutdown_event.clear()

        if self._initializing:
            return
        self._initializing = True
        self.logger.debug("Initializing %s: %s", self.role, self.unique_name)
        await self.handle_starting()
        try:
            await self._run_hooks([self.before_initialize, self.on_initialize])
            self._serve_task = self.task_bucket.spawn(self._serve_wrapper(), name=f"service:serve:{self.class_name}")
            await self._run_hooks([self.after_initialize])
            for child in self.children:
                if child.status not in (ResourceStatus.STARTING, ResourceStatus.RUNNING):
                    await child.initialize()
        finally:
            self._initializing = False

    @final
    async def shutdown(self) -> None:
        """NOTE: keep guards and flag resets in sync with Resource.shutdown()."""
        if self._shutdown_completed:
            return
        if self._shutting_down:
            return
        self._shutting_down = True
        self.request_shutdown("shutdown")
        self.logger.debug("Shutting down %s: %s", self.role, self.unique_name)
        try:
            await self._run_hooks([self.before_shutdown], continue_on_error=True)
            if self.is_running() and self._serve_task:
                self._serve_task.cancel()
                self.logger.debug("Cancelled serve() task")
                with suppress(asyncio.CancelledError):
                    await self._serve_task
            await self._run_hooks([self.on_shutdown, self.after_shutdown], continue_on_error=True)
        finally:
            await self._finalize_shutdown()
            self._shutting_down = False

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
