"""App lifecycle manager for initialization and shutdown orchestration."""

from logging import getLogger
from timeit import default_timer as timer
from typing import TYPE_CHECKING

import anyio
from humanize import precisedelta

from hassette.events.hassette import HassetteAppStateEvent
from hassette.types.enums import ResourceStatus, Topic
from hassette.utils.exception_utils import get_short_traceback

if TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app import App
    from hassette.config.classes import AppManifest
    from hassette.core.app_registry import AppRegistry

LOGGER = getLogger(__name__)

# shorten enum references
FAILED = ResourceStatus.FAILED
STARTING = ResourceStatus.STARTING
RUNNING = ResourceStatus.RUNNING
STOPPING = ResourceStatus.STOPPING
STOPPED = ResourceStatus.STOPPED


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
                await self._emit_app_state_change(inst, status=RUNNING, prev_status=STARTING)
            except TimeoutError as e:
                self.logger.error(
                    "Timed out while starting app '%s' (%s):\n%s",
                    inst.app_config.instance_name,
                    class_name,
                    get_short_traceback(5),
                )
                inst.status = STOPPED
                self.registry.record_failure(app_key, idx, e)
                await self._emit_app_state_change(inst, status=FAILED, prev_status=STARTING, exception=e)
            except Exception as e:
                self.logger.error(
                    "Failed to start app '%s' (%s):\n%s",
                    inst.app_config.instance_name,
                    class_name,
                    get_short_traceback(5),
                )
                inst.status = STOPPED
                self.registry.record_failure(app_key, idx, e)
                await self._emit_app_state_change(inst, status=FAILED, prev_status=STARTING, exception=e)

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
                "Stopped app '%s' '%s' in %s", inst.app_config.instance_name, inst.class_name, friendly_time
            )
            await self._emit_app_state_change(inst, status=STOPPED, prev_status=STOPPING)
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
        with_cleanup: bool = True,
    ) -> None:
        """Shutdown all provided app instances.

        Args:
            instances: Dict of index -> App to shutdown
            app_key: App key for logging
            with_cleanup: Whether to call cleanup() after shutdown
        """
        if not instances:
            return

        self.logger.debug("Stopping %d app instances", len(instances))

        for inst in instances.values():
            event = HassetteAppStateEvent.from_data(app=inst, status=STOPPING, previous_status=RUNNING)
            await self.hassette.send_event(Topic.HASSETTE_EVENT_APP_STATE_CHANGED, event)
            await self.shutdown_instance(inst, with_cleanup=with_cleanup)

    async def shutdown_all(self) -> None:
        """Shutdown all registered apps."""
        self.logger.debug("Shutting down all apps")

        for instances in self.registry.apps.values():
            await self.shutdown_instances(instances, with_cleanup=True)

        self.registry.clear_all()

    async def _emit_app_state_change(
        self,
        app: "App[AppConfig]",
        status: ResourceStatus,
        prev_status: ResourceStatus | None = None,
        exception: Exception | BaseException | None = None,
    ) -> None:
        event = HassetteAppStateEvent.from_data(
            app=app, status=status, previous_status=prev_status, exception=exception
        )
        await self.hassette.send_event(Topic.HASSETTE_EVENT_APP_STATE_CHANGED, event)
