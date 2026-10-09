"""AppInstanceLifecycleMixin — per-instance initialization, cleanup, shutdown, and state-event emission."""

import typing
from collections.abc import Awaitable, Callable
from logging import Logger
from timeit import default_timer as timer

import anyio
import structlog.contextvars
from hassette_wire import ResourceStatus

from hassette.core.app_lifecycle_common import (
    FAILED,
    INIT_FAILURE_TRACEBACK_LIMIT,
    RUNNING,
    STARTING,
    STOPPED,
    STOPPING,
)
from hassette.events.hassette import HassetteAppStateEvent
from hassette.resources.lifecycle import mark_ready
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app.app import App
    from hassette.config.classes import AppManifest
    from hassette.core.app_registry import AppRegistry

try:
    from humanize import precisedelta
except ImportError:  # pragma: no cover
    precisedelta = None  # pyright: ignore[reportAssignmentType]


class AppInstanceLifecycleMixin:
    """Per-instance initialization, cleanup, shutdown, and state-event emission for ``AppLifecycleService``."""

    # Provided by the AppLifecycleService host (its own body, Resource, or a sibling mixin);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    registry: "AppRegistry"
    startup_timeout: int
    shutdown_timeout: int
    cleanup_timeout: int
    reconcile_app_registrations: Callable[..., Awaitable[None]]

    async def initialize_instances(
        self,
        app_key: str,
        instances: dict[int, "App[AppConfig]"],
        manifest: "AppManifest",
        instance_index: int | None = None,
        only_indices: set[int] | None = None,
    ) -> None:
        """Initialize instances for an app key.

        Records failures directly to the registry. After all instances are
        initialized, awaits pending DB registrations and runs post-ready
        reconciliation to retire stale rows from previous sessions.

        Args:
            app_key: The app key
            instances: Dict of index -> App. Used for both the initialization loop (filtered
                by ``only_indices`` when provided) and post-ready reconciliation (always uses
                the full dict so that pre-existing instances' listener/job rows are not retired).
            manifest: The app manifest
            instance_index: When provided, scopes post-ready reconciliation to this instance
                only, so restarting one instance does not retire sibling instances' rows.
                When None (default), reconciliation is app_key-scoped only — unchanged behavior.
            only_indices: When provided, only instances at these indices are initialized.
                Others are skipped but still included in reconciliation.
        """
        class_name = manifest.class_name

        for idx, inst in instances.items():
            if only_indices is not None and idx not in only_indices:
                continue
            structlog.contextvars.bind_contextvars(
                app_key=app_key,
                instance_name=inst.app_config.instance_name,
                instance_index=idx,
            )
            try:
                with anyio.fail_after(self.startup_timeout):
                    await inst.initialize()
                    mark_ready(inst, reason="initialized")
                self.logger.debug(
                    "App '%s' (%s) initialized successfully",
                    inst.app_config.instance_name,
                    class_name,
                )
                await self.emit_app_state_change(inst, status=RUNNING, previous_status=STARTING)
            except TimeoutError as exc:
                self.logger.error(
                    "Timed out while starting app '%s' (%s):\n%s",
                    inst.app_config.instance_name,
                    class_name,
                    get_short_traceback(-INIT_FAILURE_TRACEBACK_LIMIT),
                )
                inst.status = STOPPED
                await self.cleanup_failed_instance(inst)
                self.registry.record_failure(app_key, idx, exc)
                await self.emit_app_state_change(inst, status=FAILED, previous_status=STARTING, exception=exc)
            except Exception as exc:
                self.logger.error(
                    "Failed to start app '%s' (%s):\n%s",
                    inst.app_config.instance_name,
                    class_name,
                    get_short_traceback(-INIT_FAILURE_TRACEBACK_LIMIT),
                )
                inst.status = STOPPED
                await self.cleanup_failed_instance(inst)
                self.registry.record_failure(app_key, idx, exc)
                await self.emit_app_state_change(inst, status=FAILED, previous_status=STARTING, exception=exc)
            finally:
                structlog.contextvars.unbind_contextvars("app_key", "instance_name", "instance_index")

        # Post-ready reconciliation: retire stale rows from previous sessions.
        # Runs after the instance loop to ensure all registrations are complete.
        await self.reconcile_app_registrations(app_key, instances, instance_index=instance_index)

    async def cleanup_failed_instance(self, inst: "App[AppConfig]") -> None:
        """Remove bus listeners and scheduler jobs registered by an instance that failed to initialize.

        Bounded by a short timeout so a broken cleanup path cannot turn an init failure into a hang.
        Must run before record_failure, which pops the instance from the registry — after that point,
        the normal shutdown path can never reach these registrations.
        """
        try:
            with anyio.fail_after(self.cleanup_timeout):
                try:
                    inst.bus.remove_all_listeners()
                except Exception:
                    self.logger.warning(
                        "Listener cleanup failed for instance '%s'",
                        inst.app_config.instance_name,
                        exc_info=True,
                    )
                try:
                    # Goes straight to Scheduler.remove_all_jobs() rather than scanning the
                    # full registry by owner string — the per-app Scheduler already holds its
                    # owned jobs (including waiting, completed, and manual jobs that never
                    # touch the heap) in _jobs_by_name, and remove_all_jobs() is the same
                    # identity-checked, registry-aware path the normal shutdown uses
                    # (Scheduler.on_shutdown). A heap-only scan would miss those jobs and leak
                    # their entity-watch subscriptions.
                    #
                    # Also deregisters the removal callback, mirroring on_shutdown()'s second
                    # statement — remove_all_jobs() itself never does this (hassette/testing/_reset.py
                    # calls it on a Scheduler instance meant to be reused across tests, where
                    # deregistering would silently break future job removals on that instance).
                    # A failed-init instance is discarded, not reused: Scheduler.__init__
                    # registers this callback unconditionally, before on_initialize ever runs,
                    # so a failed instance always has one registered, and nothing here will
                    # reuse this Scheduler object afterward — skipping the deregister would
                    # leak the stale callback (and the Scheduler it closes over) in
                    # SchedulerService._removal_callbacks until/unless a future instance for
                    # the same owner_id happens to overwrite that dict entry.
                    await inst.scheduler.remove_all_jobs()
                    inst.scheduler.scheduler_service.deregister_removal_callback(inst.scheduler.owner_id)
                except Exception:
                    self.logger.warning(
                        "Job cleanup failed for instance '%s'",
                        inst.app_config.instance_name,
                        exc_info=True,
                    )
                try:
                    await inst.cache.close()
                except Exception:
                    self.logger.warning(
                        "Cache cleanup failed for instance '%s'",
                        inst.app_config.instance_name,
                        exc_info=True,
                    )
        except TimeoutError:
            self.logger.warning(
                "Cleanup timed out for failed instance '%s' — some listeners or jobs may leak until restart",
                inst.app_config.instance_name,
            )

    async def shutdown_instance(self, inst: "App[AppConfig]", instance_index: int | None = None) -> None:
        """Shutdown a single app instance.

        Args:
            inst: The app instance to shutdown
            instance_index: Instance index for correlation ID binding. When provided, app identity
                context vars are bound for the duration of the shutdown call so all log records
                emitted during on_shutdown carry app identity.
        """
        if instance_index is not None:
            structlog.contextvars.bind_contextvars(
                app_key=inst.app_key,
                instance_name=inst.app_config.instance_name,
                instance_index=instance_index,
            )
        try:
            start_time = timer()
            with anyio.fail_after(self.shutdown_timeout):
                await inst.shutdown()

            end_time = timer()
            if precisedelta is not None:
                friendly_time = precisedelta(end_time - start_time, minimum_unit="milliseconds")
            else:
                friendly_time = f"{end_time - start_time:.3f}s"
            self.logger.debug(
                "Stopped app '%s' '%s' in %s", inst.app_config.instance_name, inst.class_name, friendly_time
            )
            await self.emit_app_state_change(inst, status=STOPPED, previous_status=STOPPING)
        except Exception as exc:
            self.logger.error(
                "Failed to stop app '%s' after %s seconds:\n%s",
                inst.app_config.instance_name,
                self.shutdown_timeout,
                get_short_traceback(),
            )
            await self.emit_app_state_change(inst, status=FAILED, previous_status=STOPPING, exception=exc)
        finally:
            if instance_index is not None:
                structlog.contextvars.unbind_contextvars("app_key", "instance_name", "instance_index")

    async def shutdown_instances(
        self,
        instances: dict[int, "App[AppConfig]"],
    ) -> None:
        """Shutdown all provided app instances.

        Args:
            instances: Dict of index -> App to shutdown
        """
        if not instances:
            return

        self.logger.debug("Stopping %d app instances", len(instances))

        for idx, inst in instances.items():
            event = HassetteAppStateEvent.from_app(app=inst, status=STOPPING, previous_status=inst.status)
            await self.hassette.send_event(event)
            await self.shutdown_instance(inst, instance_index=idx)

    async def shutdown_all(self) -> None:
        """Shutdown all registered apps."""
        self.logger.debug("Shutting down all apps")

        for app_key in self.registry.app_keys():
            await self.shutdown_instances(self.registry.get_running_apps(app_key))

        self.registry.clear_all()

    async def emit_app_state_change(
        self,
        app: "App[AppConfig]",
        status: ResourceStatus,
        previous_status: ResourceStatus | None = None,
        exception: Exception | BaseException | None = None,
    ) -> None:
        """Emit an app state change event via Hassette's event system."""
        event = HassetteAppStateEvent.from_app(
            app=app, status=status, previous_status=previous_status, exception=exception
        )
        await self.hassette.send_event(event)
