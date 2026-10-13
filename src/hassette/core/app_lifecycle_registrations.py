"""AppRegistrationReconcilerMixin — telemetry-registration reconciliation and removed-app retirement."""

import typing
from logging import Logger

import anyio

from hassette.core.app_lifecycle_common import REMOVED_APP_RETIRE_TIMEOUT_SECONDS

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app.app import App
    from hassette.core.app_registry import AppRegistry
    from hassette.core.bus_service import BusService


class AppRegistrationReconcilerMixin:
    """Post-ready telemetry-registration reconciliation for ``AppLifecycleService``."""

    # Provided by the AppLifecycleService host (its own body, Resource, or a sibling mixin);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    registry: "AppRegistry"

    def collect_live_listener_ids(self, app_key: str, instances: "dict[int, App[AppConfig]]") -> set[int]:
        """Collect listener db_ids registered by all instances.

        Registration is synchronous with the DB — db_ids are set before on_initialize() returns.
        """
        live_listener_ids: set[int] = set()
        for inst in instances.values():
            try:
                for listener in inst.bus.get_listeners():
                    if listener.db_id is not None:
                        live_listener_ids.add(listener.db_id)
            except Exception:
                self.logger.warning(
                    "Failed to collect listener IDs from app '%s' instance — proceeding with partial set",
                    app_key,
                )
        return live_listener_ids

    def merge_router_listener_ids(
        self,
        app_key: str,
        instances: "dict[int, App[AppConfig]]",
        bus_service: "BusService",
        live_listener_ids: set[int],
    ) -> set[int]:
        """Union in listener db_ids the Router knows are active.

        Avoids retiring rows for mid-session active handlers that ``collect_live_listener_ids``
        may have missed. Returns a new set rather than mutating ``live_listener_ids``.
        """
        try:
            router = bus_service.router
            router_ids: set[int] = set()
            for inst in instances.values():
                for listener in router.get_listeners_by_owner(inst.bus.owner_id):
                    if listener.db_id is not None:
                        router_ids.add(listener.db_id)
            return live_listener_ids | router_ids
        except Exception:
            self.logger.warning(
                "Router safety guard failed for app '%s' — proceeding with collected live IDs only",
                app_key,
            )
            return live_listener_ids

    def collect_live_job_ids(self, app_key: str, instances: "dict[int, App[AppConfig]]") -> list[int]:
        """Collect scheduled-job db_ids registered by all instances."""
        live_job_ids: list[int] = []
        for inst in instances.values():
            try:
                live_job_ids.extend(inst.scheduler.get_job_db_ids())
            except Exception:
                self.logger.warning(
                    "Failed to collect job IDs from app '%s' instance — proceeding with partial set",
                    app_key,
                )
        return live_job_ids

    def resolve_session_id(self, app_key: str) -> int | None:
        """Resolve the current session ID for the once=True cleanup guard.

        Returns None (degraded mode) if the session ID is unavailable — once=True
        cleanup is skipped and deferred to the next restart.
        """
        try:
            return self.hassette.session_id
        except Exception:
            self.logger.warning(
                "session_id unavailable for app '%s' — reconciliation running in degraded mode; "
                "once=True cleanup skipped (deferred to next restart)",
                app_key,
            )
            return None

    async def reconcile_app_registrations(
        self,
        app_key: str,
        instances: "dict[int, App[AppConfig]]",
        instance_index: int | None = None,
    ) -> None:
        """Run post-ready reconciliation for an app after all instances are initialized.

        Awaits pending DB registrations, collects live IDs from all instances,
        applies the Router safety guard, then calls reconcile_registrations.
        Failure is non-fatal — logs a warning and allows the app to continue.

        Args:
            app_key: The app key to reconcile.
            instances: Dict of instance index -> App (may include failed instances).
            instance_index: When provided, scopes reconciliation to this instance only, so
                restarting one instance does not retire sibling instances' rows. When None
                (default), reconciliation is app_key-scoped only — unchanged behavior.
        """
        try:
            bus_service = self.hassette.bus_service

            live_listener_ids = self.collect_live_listener_ids(app_key, instances)
            live_listener_ids = self.merge_router_listener_ids(app_key, instances, bus_service, live_listener_ids)
            live_job_ids = self.collect_live_job_ids(app_key, instances)
            session_id = self.resolve_session_id(app_key)

            await self.hassette.command_executor.reconcile_registrations(
                app_key,
                list(live_listener_ids),
                live_job_ids,
                session_id=session_id,
                instance_index=instance_index,
            )
            self.logger.debug("Post-ready reconciliation complete for app '%s'", app_key)
        except Exception:
            self.logger.warning(
                "Post-ready reconciliation failed for app '%s' — reconciliation rolled back; "
                "stale rows (including once=True cleanup) may remain until next restart",
                app_key,
                exc_info=True,
            )

    async def retire_removed_app_registrations(self) -> None:
        """Retire the telemetry registrations of every app no longer in config.

        Removed apps are never reconciled again, so without this their listener/job rows
        would stay unretired forever and retention could never prune them or their manifest.

        Precondition: no app absent from ``registry.manifests`` may still be running, or its
        live rows get retired. That holds during bootstrap (no such app was started this
        process) and once a config change has stopped its orphans; it does not hold between a
        hot reload swapping the config and those orphans stopping.

        Failure is non-fatal — logs a warning. The rows are retired by the next bootstrap or
        the next config change that removes an app.
        """
        try:
            with anyio.fail_after(REMOVED_APP_RETIRE_TIMEOUT_SECONDS):
                listeners, jobs = await self.hassette.command_executor.retire_removed_app_registrations(
                    list(self.registry.manifests)
                )
        except Exception:
            self.logger.warning(
                "Failed to retire registrations of apps removed from config — their telemetry "
                "won't be pruned until the next successful attempt",
                exc_info=True,
            )
            return
        if listeners or jobs:
            self.logger.info(
                "Retired %d listener(s) and %d scheduled job(s) of apps removed from config", listeners, jobs
            )
