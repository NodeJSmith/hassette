import asyncio
import inspect
import typing
import uuid
from abc import abstractmethod
from collections.abc import Coroutine
from contextlib import suppress
from functools import cached_property
from logging import Logger, getLogger
from typing import Any, ClassVar, TypeVar, final

from diskcache import Cache

from hassette.exceptions import CannotOverrideFinalError, FatalError
from hassette.types.enums import ResourceRole

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

        # Collect all methods marked as final from the MRO (excluding object and cls itself)
        finals: dict[str, type] = {}
        for ancestor in cls.__mro__[1:]:
            if ancestor is object:
                continue
            for attr, obj in ancestor.__dict__.items():
                if getattr(obj, "__final__", False):
                    finals.setdefault(attr, ancestor)

        # Check for overrides in the subclass namespace
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

    @classmethod
    def create(
        cls, hassette: "Hassette", task_bucket: "TaskBucket | None" = None, parent: "Resource | None" = None, **kwargs
    ):
        sig = inspect.signature(cls)
        # Start with a copy of incoming kwargs to preserve any extra arguments
        final_kwargs = dict(kwargs)
        if "hassette" in sig.parameters:
            final_kwargs["hassette"] = hassette
        if "task_bucket" in sig.parameters:
            final_kwargs["task_bucket"] = task_bucket
        if "parent" in sig.parameters:
            final_kwargs["parent"] = parent
        return cls(**final_kwargs)

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
            self.task_bucket = task_bucket or TaskBucket.create(self.hassette, parent=self)

    def _setup_logger(self) -> None:
        logger_name = (
            self.unique_name[len("Hassette.") :] if self.unique_name.startswith("Hassette.") else self.unique_name
        )
        if self.class_name == "Hassette":
            self.logger = getLogger("hassette")
        else:
            self.logger = getLogger("hassette").getChild(logger_name)
        self.logger.debug("Creating instance")
        self.logger.setLevel(self.config_log_level)

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

        sig = inspect.signature(child_class.create)
        if "parent" in sig.parameters:
            kwargs["parent"] = self

        if "hassette" not in sig.parameters:
            raise ValueError("Child resource class must accept 'hassette' argument in its create() method.")

        inst = child_class.create(self.hassette, **kwargs)
        self.children.append(inst)
        return inst

    @final
    async def initialize(self) -> None:
        """Initialize the instance by calling the lifecycle hooks in order."""
        if self._initializing:
            return
        self._initializing = True

        self.logger.setLevel(self.config_log_level)
        self.logger.debug("Initializing %s: %s", self.role, self.unique_name)
        await self.handle_starting()

        try:
            for method in [self.before_initialize, self.on_initialize, self.after_initialize]:
                try:
                    await method()

                except asyncio.CancelledError:
                    # Cooperative cancellation of hooks; still ensure cleanup + STOPPED
                    with suppress(Exception):
                        await self.handle_failed(asyncio.CancelledError())
                    raise

                except Exception as e:
                    # Hooks blew up: record failure, but continue to clean up
                    with suppress(Exception):
                        await self.handle_failed(e)
                    raise

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
        """Shutdown the instance by calling the lifecycle hooks in order."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self.request_shutdown("shutdown")
        self.logger.debug("Shutting down %s: %s", self.role, self.unique_name)

        try:
            for method in [self.before_shutdown, self.on_shutdown, self.after_shutdown]:
                try:
                    await method()

                except asyncio.CancelledError:
                    self.logger.warning("Shutdown hook was cancelled, forcing cleanup")
                    # Cooperative cancellation of hooks; still ensure cleanup + STOPPED
                    with suppress(Exception):
                        await self.handle_failed(asyncio.CancelledError())
                    raise

                except Exception as e:
                    self.logger.exception("Error during shutdown: %s %s", type(e).__name__, e)
                    # Hooks blew up: record failure, but continue to clean up
                    with suppress(Exception):
                        await self.handle_failed(e)

        finally:
            # Always free tasks; then mark STOPPED and emit event
            try:
                await self.cleanup()
            except Exception as e:
                self.logger.exception("Error during cleanup: %s %s", type(e).__name__, e)

            if not self.hassette.event_streams_closed:
                try:
                    await self.handle_stop()
                except Exception as e:
                    self.logger.exception("Error during stopping %s %s", type(e).__name__, e)
            else:
                self.logger.debug("Skipping STOPPED event as event streams are closed")

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
    """Base class for services in the Hassette framework."""

    role: ClassVar[ResourceRole] = ResourceRole.SERVICE
    """Role of the service, e.g. 'App', 'Service', etc."""

    _serve_task: asyncio.Task | None = None

    @abstractmethod
    async def serve(self) -> None:
        """Subclasses MUST override: run until cancelled or finished."""
        raise NotImplementedError

    # Start: spin up the supervised serve() task
    async def on_initialize(self) -> None:
        # Do any service-specific setup, then launch serve()
        self._serve_task = self.task_bucket.spawn(self._serve_wrapper(), name=f"service:serve:{self.class_name}")

    async def _serve_wrapper(self) -> None:
        try:
            # We're “RUNNING” as soon as on_initialize returns; readiness is up to the service
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
            self.logger.exception("Serve() task failed: %s %s", type(e).__name__, e)
            # Crash/failure path
            await self.handle_failed(e)

    # Shutdown: cancel the serve() task and wait for it
    async def on_shutdown(self) -> None:
        # Flip any internal flags if you have them; then cancel the loop
        if self.is_running() and self._serve_task:
            self._serve_task.cancel()
            self.logger.debug("Cancelled serve() task")
            with suppress(asyncio.CancelledError):
                await self._serve_task

    def is_running(self) -> bool:
        return self._serve_task is not None and not self._serve_task.done()
