import logging
import typing
from logging import getLogger
from typing import Any, ClassVar, Generic

from anyio import to_thread

from hassette.config.app_manifest import AppManifest
from hassette.core.bus import Bus
from hassette.core.classes.resource import Resource
from hassette.core.enums import ResourceRole
from hassette.core.events import Event
from hassette.core.scheduler import Scheduler

from .app_config import AppConfig, AppConfigT
from .utils import validate_app

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette

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

    scheduler: Scheduler
    """Scheduler instance for scheduled tasks owned by this app."""

    bus: Bus
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

    def __init__(
        self,
        hassette: "Hassette",
        app_config: AppConfigT,
        index: int = 0,
        *args,
        **kwargs,
    ):
        """Initialize the App instance. This will generally not be called directly.

        Args:
            hassette (Hassette): The Hassette instance this app belongs to.
            app_config (AppConfigT): User configuration for the app, defaults to AppUserConfig.
            index (int): Index of the app instance, used when multiple instances of the same app are run.

        """
        self.app_config = app_config
        self.index = index

        super().__init__(hassette=hassette, *args, **kwargs)  # noqa: B026

        logger_name = f"hassette.{type(self).__name__}.{self.app_config.instance_name}"
        self.logger = getLogger(logger_name)

        if self.instance_name == "":
            # this shouldn't happen, as AppHandler will set a default if not provided
            raise ValueError("App instance_name cannot be empty.")

        self.bus = Bus(self.hassette, owner=self.unique_name)
        self.scheduler = Scheduler(self.hassette, owner=self.unique_name)

    @property
    def unique_name(self) -> str:
        """Unique identifier for the instance."""
        return f"{self.class_name}-{self.instance_name}-{self.unique_id}"

    @property
    def instance_name(self) -> str:
        """Name for the instance of the app. Used for logging and ownership of resources."""
        return self.app_config.instance_name

    @property
    def api(self):
        """API instance for interacting with Home Assistant."""
        return self.hassette.api

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

    def cleanup_resources(self) -> None:
        """Cleanup resources owned by the app.

        This method is called during shutdown to ensure that all resources are properly released.
        """
        self.scheduler.remove_all_jobs()
        self.bus.remove_all_listeners()
        self.logger.debug("Cleaned up resources for app '%s'", self.class_name)


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
