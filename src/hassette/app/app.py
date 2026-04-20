import logging
import typing
from logging import getLogger
from typing import Any, ClassVar, Generic, cast, final

from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.api import Api
from hassette.bus import Bus
from hassette.config.classes import AppManifest
from hassette.events.base import Event
from hassette.resources.base import FinalMeta, Resource
from hassette.scheduler import Scheduler
from hassette.state_manager import StateManager
from hassette.types import AppConfigT
from hassette.types.enums import ResourceRole
from hassette.types.types import LOG_LEVEL_TYPE, SourceTier

from .app_config import AppConfig

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
    app_cls._only_app = True
    return app_cls


class App(Generic[AppConfigT], Resource, metaclass=FinalMeta):
    """Base class for applications in the Hassette framework.

    This class provides a structure for applications, allowing them to be initialized and managed
    within the Hassette ecosystem. Lifecycle will generally be managed for you via the service status events,
    which send an event to the Bus and set the `status` attribute, based on the app's lifecycle.
    """

    _only_app: ClassVar[bool] = False
    """If True, only this app will be run. Only one app can be marked as only."""

    _import_exception: ClassVar[Exception | None] = None
    """Exception raised during import, if any. This prevents having all apps in a module fail due to one exception."""

    _api_factory: ClassVar[type[Resource] | None] = None
    """Internal: factory for the Api resource. When set, App.__init__ uses this instead of Api.
    Used by AppTestHarness to inject RecordingApi. Not a user-facing API."""

    role: ClassVar[ResourceRole] = ResourceRole.APP
    """Role of the resource, e.g. 'App', 'Service', etc."""

    source_tier: ClassVar[SourceTier] = "app"

    app_manifest: ClassVar[AppManifest]
    "Manifest for the app itself, not used by app instances."

    app_config_cls: ClassVar[type[AppConfig]]
    """Config class to use for instances of the created app. Configuration from hassette.toml or
    other sources will be validated by this class."""

    logger: logging.Logger
    """Logger for the instance."""

    api: "Api"
    """API instance for interacting with Home Assistant."""

    scheduler: "Scheduler"
    """Scheduler instance for scheduled tasks owned by this app."""

    bus: "Bus"
    """Event bus instance for event handlers owned by this app."""

    states: "StateManager"
    """States manager instance for accessing Home Assistant states."""

    app_config: AppConfigT
    """Configuration for this app instance."""

    index: int
    """Index of this app instance, used for unique naming."""

    def __init__(
        self, hassette: "Hassette", *, app_config: AppConfigT, index: int, parent: Resource | None = None
    ) -> None:
        # app_config and index must be set before super().__init__ because
        # unique_name (used by the logger) depends on app_config
        self.app_config = app_config
        self.index = index
        super().__init__(hassette, parent=parent)
        factory = type(self)._api_factory or Api
        self.api = cast("Api", self.add_child(factory))
        self.scheduler = self.add_child(Scheduler)
        self.bus = self.add_child(Bus, priority=0)
        self.states = self.add_child(StateManager)

    @property
    def unique_name(self) -> str:
        """Unique name for the app instance, used for logging and ownership of resources."""
        if self.app_config.instance_name.startswith(self.class_name):
            return self.app_config.instance_name
        return f"{self.class_name}.{self.app_config.instance_name}"

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        try:
            return self.app_config.log_level
        except AttributeError:
            return self.hassette.config.apps_log_level

    @property
    def app_key(self) -> str:
        """Key for this app in the hassette.toml configuration."""
        return self.app_manifest.app_key

    @property
    def instance_name(self) -> str:
        """Name for the instance of the app. Used for logging and ownership of resources."""
        return self.app_config.instance_name

    def now(self) -> ZonedDateTime:
        """Return the current date and time."""
        return date_utils.now()

    async def send_event(self, event_name: str, event: Event[Any]) -> None:
        """Send an event to the event bus."""
        await self.hassette.send_event(event_name, event)

    @final
    async def cleanup(self, timeout: int | None = None) -> None:
        """Cleanup resources owned by the instance.

        This method is called during shutdown to cancel tasks and close caches.
        Child cleanup (Bus, Scheduler, etc.) is handled by _finalize_shutdown() propagation,
        not by this method.
        """
        timeout = timeout or self.hassette.config.app_shutdown_timeout_seconds
        await super().cleanup(timeout=timeout)


class AppSync(App[AppConfigT]):
    """Synchronous adapter for App."""

    def send_event_sync(self, event_name: str, event: Event[Any]) -> None:
        """Synchronous version of send_event."""
        self.task_bucket.run_sync(self.send_event(event_name, event))

    @final
    async def before_shutdown(self) -> None:
        """Optional: stop accepting new work, signal loops to wind down, etc."""
        await self.task_bucket.run_in_thread(self.before_shutdown_sync)

    @final
    async def on_shutdown(self) -> None:
        """Primary hook: release your own stuff (sockets, queues, temp files…)."""
        await self.task_bucket.run_in_thread(self.on_shutdown_sync)

    @final
    async def after_shutdown(self) -> None:
        """Optional: last-chance actions after on_shutdown, before cleanup/STOPPED."""
        await self.task_bucket.run_in_thread(self.after_shutdown_sync)

    @final
    async def before_initialize(self) -> None:
        """Optional: prepare to accept new work, allocate sockets, queues, temp files, etc."""
        await self.task_bucket.run_in_thread(self.before_initialize_sync)

    @final
    async def on_initialize(self) -> None:
        """Primary hook: perform your own initialization (sockets, queues, temp files…)."""
        await self.task_bucket.run_in_thread(self.on_initialize_sync)

    @final
    async def after_initialize(self) -> None:
        """Optional: finalize initialization, signal readiness, etc."""
        await self.task_bucket.run_in_thread(self.after_initialize_sync)

    def before_shutdown_sync(self) -> None:
        """Optional: stop accepting new work, signal loops to wind down, etc."""
        pass

    def on_shutdown_sync(self) -> None:
        """Primary hook: release your own stuff (sockets, queues, temp files…)."""
        pass

    def after_shutdown_sync(self) -> None:
        """Optional: last-chance actions after on_shutdown, before cleanup/STOPPED."""
        pass

    def before_initialize_sync(self) -> None:
        """Optional: prepare to accept new work, allocate sockets, queues, temp files, etc."""
        pass

    def on_initialize_sync(self) -> None:
        """Primary hook: perform your own initialization (sockets, queues, temp files…)."""
        pass

    def after_initialize_sync(self) -> None:
        """Optional: finalize initialization, signal readiness, etc."""
        pass

    @final
    def initialize_sync(self) -> None:
        """Use on_initialize_sync instead."""
        raise NotImplementedError("Use on_initialize_sync instead.")

    @final
    def shutdown_sync(self) -> None:
        """Use on_shutdown_sync instead."""
        raise NotImplementedError("Use on_shutdown_sync instead.")
