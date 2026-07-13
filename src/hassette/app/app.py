import typing
from logging import Logger, getLogger
from typing import ClassVar, Generic, TypeVar, cast, final

from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.api import Api
from hassette.bus import Bus
from hassette.config.classes import AppManifest
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

AppT = TypeVar("AppT", bound="App")

_APP_PUBLIC_API: frozenset[str] = frozenset(
    {
        "logger",
        "api",
        "scheduler",
        "bus",
        "states",
        "app_config",
        "instance_name",
        "unique_name",
        "index",
        "now",
        "on_initialize",
        "on_shutdown",
        "before_initialize",
        "after_initialize",
        "before_shutdown",
        "after_shutdown",
        "task_bucket",
        "cache",
        "is_ready",
        "wait_ready",
    }
)
"""App-author API allowlist — see design/specs/010-lifecycle-extraction/design.md.

`App.__dir__` returns only these names, hiding the ~34 framework-internal names
(lifecycle state transitions, child-resource wiring, readiness signaling) that
Resource and LifecycleMixin otherwise expose.
"""

_APPSYNC_HOOKS: frozenset[str] = frozenset(
    {
        "before_initialize_sync",
        "on_initialize_sync",
        "after_initialize_sync",
        "before_shutdown_sync",
        "on_shutdown_sync",
        "after_shutdown_sync",
    }
)
"""AppSync's additional app-author-visible sync hooks, layered on top of `_APP_PUBLIC_API`."""


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

    role: ClassVar[ResourceRole] = ResourceRole.APP
    """Role of the resource, e.g. 'App', 'Service', etc."""

    source_tier: ClassVar[SourceTier] = "app"

    app_manifest: AppManifest | None
    """Manifest describing this app instance, set at construction from its config section.

    Stored per instance, not on the class: two config sections can point at the same
    App subclass, so each instance carries its own manifest rather than reading a
    class-shared one — otherwise the section loaded last would overwrite display_name,
    enabled, and auto_loaded for every instance. Mirrors how app_key is stored per
    instance. None only when an App is constructed directly without a manifest; the
    factory and the test harness both pass one.
    """

    app_config_cls: ClassVar[type[AppConfig]]
    """Config class to use for instances of the created app. Configuration from hassette.toml or
    other sources will be validated by this class."""

    logger: Logger
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
        self,
        hassette: "Hassette",
        *,
        app_config: AppConfigT,
        index: int,
        app_key: str,
        app_manifest: AppManifest | None = None,
        api_factory: type[Resource] | None = None,
        parent: Resource | None = None,
    ) -> None:
        # app_config and index must be set before super().__init__ because
        # unique_name (used by the logger) depends on app_config
        self.app_config = app_config
        self.index = index
        self._app_key = app_key
        self.app_manifest = app_manifest
        super().__init__(hassette, parent=parent)
        self.api = cast("Api", self.add_child(api_factory or Api))
        self.scheduler = self.add_child(Scheduler)
        self.bus = self.add_child(Bus, priority=0)
        self.states = self.add_child(StateManager)

    def __dir__(self) -> list[str]:
        return sorted(_APP_PUBLIC_API)

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
            return self.hassette.config.logging.apps

    @property
    def app_key(self) -> str:
        """Key for this app in the hassette.toml configuration.

        Set per instance at construction. Two config sections can point at the same
        App subclass, so each instance stores its own key — reading it from a
        class-shared attribute would let the last section loaded clobber it for all.
        """
        return self._app_key

    @property
    def instance_name(self) -> str:
        """Name for the instance of the app. Used for logging and ownership of resources."""
        return self.app_config.instance_name

    def now(self) -> ZonedDateTime:
        """Return the current date and time."""
        return date_utils.now()

    @final
    async def cleanup(self, timeout: float | None = None) -> None:
        """Cleanup resources owned by the instance.

        This method is called during shutdown to cancel tasks and close caches.
        Child cleanup (Bus, Scheduler, etc.) is handled by _finalize_shutdown() propagation,
        not by this method.
        """
        timeout = timeout or self.hassette.config.lifecycle.app_shutdown_timeout_seconds
        await super().cleanup(timeout=timeout)


class AppSync(App[AppConfigT]):
    """Synchronous adapter for App."""

    def __dir__(self) -> list[str]:
        return sorted(_APP_PUBLIC_API | _APPSYNC_HOOKS)

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
