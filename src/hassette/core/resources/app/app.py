import asyncio
import logging
import typing
from collections.abc import Coroutine
from logging import getLogger
from typing import Any, ClassVar, Generic

from anyio import to_thread

from hassette.config.app_manifest import AppManifest
from hassette.core.resources.api import Api
from hassette.core.resources.base import Resource
from hassette.core.resources.bus.bus import Bus
from hassette.core.resources.scheduler.scheduler import Scheduler
from hassette.enums import ResourceRole
from hassette.events.base import Event

from .app_config import AppConfig, AppConfigT
from .utils import validate_app

if typing.TYPE_CHECKING:
    from hassette import Hassette


LOGGER = getLogger(__name__)

AppT = typing.TypeVar("AppT", bound="App")


def only_app(app_cls: type[AppT]) -> type[AppT]:
    """Decorator to mark an app class as the only one to run. If more than one app is marked with this decorator,
    an exception will be raised during initialization.

    This is useful for development and testing, where you may want to run only a specific app without
    modifying configuration files.
    """
    app_cls._only_app = True  # type: ignore[attr-defined]
    return app_cls


class App(Generic[AppConfigT], Resource):
    """Base class for applications in the Hassette framework.

    This class provides a structure for applications, allowing them to be initialized and managed
    within the Hassette ecosystem. Lifecycle will generally be managed for you via the service status events,
    which send an event to the Bus and set the `status` attribute, based on the app's lifecycle.
    """

    _only_app: ClassVar[bool] = False
    """If True, only this app will be run. Only one app can be marked as only."""

    role: ClassVar[ResourceRole] = ResourceRole.APP
    """Role of the resource, e.g. 'App', 'Service', etc."""

    app_manifest: ClassVar[AppManifest]
    "Manifest for the app itself, not used by app instances."

    app_config_cls: ClassVar[type[AppConfig]]
    """Config class to use for instances of the created app. Configuration from hassette.toml or
    other sources will be validated by this class."""

    _import_exception: ClassVar[Exception | None] = None
    """Exception raised during import, if any. This prevents having all apps in a module fail due to one exception."""

    logger: logging.Logger
    """Logger for the instance."""

    api: "Api"
    """API instance for interacting with Home Assistant."""

    scheduler: "Scheduler"
    """Scheduler instance for scheduled tasks owned by this app."""

    bus: "Bus"
    """Event bus instance for event handlers owned by this app."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        try:
            cls.app_config_cls = validate_app(cls)

        except Exception as e:
            # note: because these are imported dynamically, we cannot do anything to prevent logging
            # the same class multiple times; likely won't be an issue in practice
            cls._import_exception = e
            LOGGER.exception("Failed to initialize subclass %s", cls.__name__)

    def __init__(self, hassette: "Hassette", app_config: AppConfigT, index: int = 0):
        """Initialize the App instance. This will generally not be called directly.

        Args:
            hassette (Hassette): The Hassette instance this app belongs to.
            app_config (AppConfigT): User configuration for the app, defaults to AppUserConfig.
            index (int): Index of the app instance, used when multiple instances of the same app are run.

        """
        super().__init__(hassette=hassette, unique_name_prefix=f"{self.class_name}.{app_config.instance_name}")

        self.app_config = app_config
        self.index = index

        # set appropriate log level
        if "log_level" in self.app_config.model_fields_set:
            # if the user set a log level for this app instance, use it
            self.logger.setLevel(app_config.log_level)
            self.logger.debug(
                "Set log level for app '%s' to '%s' from instance config", self.class_name, app_config.log_level
            )
        else:
            self.logger.setLevel(self.hassette.config.apps_log_level)

        self.bus = Bus(self.hassette, owner=f"{self.unique_name}.bus", task_bucket=self.task_bucket)
        self.scheduler = Scheduler(self.hassette, owner=f"{self.unique_name}.scheduler", task_bucket=self.task_bucket)
        self.api = Api(self.hassette, unique_name_prefix=f"{self.unique_name}.api", task_bucket=self.task_bucket)

    @property
    def instance_name(self) -> str:
        """Name for the instance of the app. Used for logging and ownership of resources."""
        return self.app_config.instance_name

    async def send_event(self, event_name: str, event: Event[Any]) -> None:
        """Send an event to the event bus."""
        await self.hassette._send_stream.send((event_name, event))

    async def initialize(self) -> None:
        """Initialize the app.

        This method should be overridden by subclasses to provide custom initialization logic.
        """
        await super().initialize()
        self.logger.info("App '%s' initialized", self.class_name)

    async def shutdown(self) -> None:
        """Shutdown the app.

        This method should be overridden by subclasses to provide custom shutdown logic.
        """
        await super().shutdown()

    def cleanup_resources(self) -> list[asyncio.Task | Coroutine]:
        """Cleanup resources owned by the app.

        This method is called during shutdown to ensure that all resources are properly released.
        """
        sched_task = self.scheduler.remove_all_jobs()
        bus_task = self.bus.remove_all_listeners()
        bucket_task = self.task_bucket.cancel_all()
        self.logger.debug("Triggered resource cleanup for app '%s'", self.class_name)
        return [sched_task, bus_task, bucket_task]

    async def wait_for_resource_cleanup(self, timeout: int | float = 10) -> None:
        """Wait for all resources owned by the app to be cleaned up.

        Args:
            timeout (int | float): Maximum time to wait for cleanup, in seconds.
        """
        tasks = self.cleanup_resources()
        if tasks:
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error("Error during resource cleanup for app '%s': %s", self.class_name, result)
        self.logger.info("All resources cleaned up for app '%s'", self.class_name)


class AppSync(App[AppConfigT]):
    """Synchronous adapter for App.

    This class allows synchronous apps to work properly in the async environment
    by using anyio's thread management capabilities.
    """

    async def initialize(self) -> None:
        """Initialize the app in a thread-safe manner."""
        # Call Resource.initialize() to handle status events
        await Resource.initialize(self)

        # Run the sync initialize method in a thread
        await to_thread.run_sync(self.initialize_sync)

    async def shutdown(self) -> None:
        """Shutdown the app in a thread-safe manner."""
        # Run the sync shutdown method in a thread
        await to_thread.run_sync(self.shutdown_sync)

        # Call Resource.shutdown() to handle status events
        await Resource.shutdown(self)

    def initialize_sync(self) -> None:
        """Synchronous initialization method to be overridden by subclasses.

        This method runs in a separate thread and can safely perform blocking operations.
        """
        pass

    def shutdown_sync(self) -> None:
        """Synchronous shutdown method to be overridden by subclasses.

        This method runs in a separate thread and can safely perform blocking operations.
        """
        pass
