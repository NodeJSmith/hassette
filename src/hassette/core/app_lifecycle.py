"""App lifecycle manager for initialization and shutdown orchestration."""

from logging import getLogger
from timeit import default_timer as timer
from typing import TYPE_CHECKING

import anyio
from humanize import precisedelta

from hassette.types.enums import ResourceStatus
from hassette.utils.exception_utils import get_short_traceback

if TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app import App
    from hassette.config.classes import AppManifest
    from hassette.core.app_registry import AppRegistry

LOGGER = getLogger(__name__)


class AppLifecycleManager:
    """Manages app instance initialization and shutdown.

    Handles timeouts, error recording, and status transitions.
    """

    def __init__(self, hassette: "Hassette", registry: "AppRegistry") -> None:
        self.hassette = hassette
        self.registry = registry
        self.logger = getLogger(f"{__name__}.AppLifecycleManager")

    @property
    def startup_timeout(self) -> int:
        return self.hassette.config.app_startup_timeout_seconds

    @property
    def shutdown_timeout(self) -> int:
        return self.hassette.config.app_shutdown_timeout_seconds

    async def initialize_instances(
        self,
        app_key: str,
        instances: dict[int, "App[AppConfig]"],
        manifest: "AppManifest",
    ) -> None:
        """Initialize all instances for an app key.

        Records failures directly to the registry.

        Args:
            app_key: The app key
            instances: Dict of index -> App to initialize
            manifest: The app manifest
        """
        class_name = manifest.class_name

        for idx, inst in instances.items():
            try:
                with anyio.fail_after(self.startup_timeout):
                    await inst.initialize()
                    inst.mark_ready(reason="initialized")
                self.logger.debug(
                    "App '%s' (%s) initialized successfully",
                    inst.app_config.instance_name,
                    class_name,
                )
            except TimeoutError as e:
                self.logger.error(
                    "Timed out while starting app '%s' (%s):\n%s",
                    inst.app_config.instance_name,
                    class_name,
                    get_short_traceback(5),
                )
                inst.status = ResourceStatus.STOPPED
                self.registry.record_failure(app_key, idx, e)
            except Exception as e:
                self.logger.error(
                    "Failed to start app '%s' (%s):\n%s",
                    inst.app_config.instance_name,
                    class_name,
                    get_short_traceback(5),
                )
                inst.status = ResourceStatus.STOPPED
                self.registry.record_failure(app_key, idx, e)

    async def shutdown_instance(self, inst: "App[AppConfig]", with_cleanup: bool = True) -> None:
        """Shutdown a single app instance.

        Args:
            inst: The app instance to shutdown
            with_cleanup: Whether to call cleanup() after shutdown
        """
        try:
            start_time = timer()
            with anyio.fail_after(self.shutdown_timeout):
                await inst.shutdown()
                if with_cleanup:
                    await inst.cleanup()

            end_time = timer()
            friendly_time = precisedelta(end_time - start_time, minimum_unit="milliseconds")
            self.logger.debug(
                "Stopped app '%s' '%s' in %s", inst.app_config.instance_name, inst.__class__.__name__, friendly_time
            )
        except Exception:
            self.logger.error(
                "Failed to stop app '%s' after %s seconds:\n%s",
                inst.app_config.instance_name,
                self.shutdown_timeout,
                get_short_traceback(),
            )

    async def shutdown_instances(
        self,
        instances: dict[int, "App[AppConfig]"],
        app_key: str | None = None,
        with_cleanup: bool = True,
    ) -> None:
        """Shutdown all provided app instances.

        Args:
            instances: Dict of index -> App to shutdown
            app_key: Optional app key for logging
            with_cleanup: Whether to call cleanup() after shutdown
        """
        if not instances:
            return

        self.logger.debug(
            "Stopping %d instances%s",
            len(instances),
            f" of {app_key}" if app_key else "",
        )

        for inst in instances.values():
            await self.shutdown_instance(inst, with_cleanup=with_cleanup)

    async def shutdown_all(self) -> None:
        """Shutdown all registered apps."""
        self.logger.debug("Shutting down all apps")

        for app in self.registry.all_apps():
            await self.shutdown_instance(app)

        self.registry.clear_all()
