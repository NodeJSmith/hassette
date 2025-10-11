import asyncio
import logging
import typing
from logging import getLogger
from typing import Any, ClassVar, Generic

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
        await self.hassette.send_event(event_name, event)

    async def on_shutdown(self, timeout: int | float = 10) -> None:
        """Wait for all resources owned by the app to be cleaned up.

        Args:
            timeout (int | float): Maximum time to wait for cleanup, in seconds.
        """
        tasks = []

        tasks.append(self.scheduler.remove_all_jobs())
        tasks.append(self.bus.remove_all_listeners())
        tasks.append(self.task_bucket.cancel_all())
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

    # --- developer-facing hooks (override as needed) -------------------
    async def before_shutdown(self) -> None:
        """Optional: stop accepting new work, signal loops to wind down, etc."""
        await self.task_bucket.run_in_thread(self.before_shutdown_sync)

    async def on_shutdown(self) -> None:
        """Primary hook: release your own stuff (sockets, queues, temp files…)."""
        await self.task_bucket.run_in_thread(self.on_shutdown_sync)
        await super().on_shutdown()

    async def after_shutdown(self) -> None:
        """Optional: last-chance actions after on_shutdown, before cleanup/STOPPED."""
        await self.task_bucket.run_in_thread(self.after_shutdown_sync)

    # --- developer-facing hooks (override as needed) -------------------
    async def before_initialize(self) -> None:
        """Optional: prepare to accept new work, allocate sockets, queues, temp files, etc."""
        await self.task_bucket.run_in_thread(self.before_initialize_sync)

    async def on_initialize(self) -> None:
        """Primary hook: perform your own initialization (sockets, queues, temp files…)."""
        await self.task_bucket.run_in_thread(self.on_initialize_sync)

    async def after_initialize(self) -> None:
        """Optional: finalize initialization, signal readiness, etc."""
        await self.task_bucket.run_in_thread(self.after_initialize_sync)

    # --- developer-facing hooks (override as needed) -------------------
    def before_shutdown_sync(self) -> None:
        """Optional: stop accepting new work, signal loops to wind down, etc."""
        # Default: cancel an in-flight initialize() task if you used Resource.start()
        self.cancel()

    def on_shutdown_sync(self) -> None:
        """Primary hook: release your own stuff (sockets, queues, temp files…)."""
        # Default: nothing. Subclasses override when they own resources.

    def after_shutdown_sync(self) -> None:
        """Optional: last-chance actions after on_shutdown, before cleanup/STOPPED."""
        # Default: nothing.

    # --- developer-facing hooks (override as needed) -------------------
    def before_initialize_sync(self) -> None:
        """Optional: prepare to accept new work, allocate sockets, queues, temp files, etc."""
        # Default: nothing. Subclasses override when they own resources.

    def on_initialize_sync(self) -> None:
        """Primary hook: perform your own initialization (sockets, queues, temp files…)."""
        # Default: nothing. Subclasses override when they own resources.

    def after_initialize_sync(self) -> None:
        """Optional: finalize initialization, signal readiness, etc."""
        # Default: nothing. Subclasses override when they own resources.
