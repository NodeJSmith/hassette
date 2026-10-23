"""AppInstanceLifecycleMixin — per-instance initialization, cleanup, shutdown, and state-event emission."""

import asyncio
import typing
from collections.abc import Awaitable, Callable
from logging import Logger
from timeit import default_timer as timer

import anyio
import structlog.contextvars
from hassette_wire import ResourceStatus
from humanize import precisedelta

from hassette.core.app_lifecycle_common import (
    FAILED,
    INIT_FAILURE_TRACEBACK_LIMIT,
    RUNNING,
    STARTING,
    STOPPED,
    STOPPING,
)
from hassette.events.hassette import HassetteAppStateEvent
from hassette.resources.lifecycle import create_lifecycle_task, mark_ready
from hassette.resources.shutdown_deadline import deadline_in, tighten_shutdown_deadline
from hassette.resources.teardown import TeardownCause, TeardownReport, merge_teardown_reports
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app.app import App
    from hassette.config.classes import AppManifest
    from hassette.core.app_registry import AppRegistry


class AppInstanceLifecycleMixin:
    """Per-instance initialization, cleanup, shutdown, and state-event emission for ``AppLifecycleService``."""

    # Provided by the AppLifecycleService host (its own body, Resource, or a sibling mixin);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    registry: "AppRegistry"
    startup_timeout: int
    entry_deadline_seconds: float
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
                await self.remove_instance_registrations(inst)
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

    async def remove_instance_registrations(self, inst: "App[AppConfig]") -> None:
        """Remove an instance's bus listeners and scheduler jobs by owner, running no user hook.

        Shared by failed-init cleanup and an entry-deadline walk-away: both leave an instance whose own
        ``Bus`` and ``Scheduler`` teardown never ran, so nothing else would remove these.
        """
        try:
            inst.bus.remove_all_listeners()
        except Exception:
            self.logger.warning(
                "Listener cleanup failed for instance '%s'", inst.app_config.instance_name, exc_info=True
            )
        try:
            # Goes straight to Scheduler.remove_all_jobs() rather than scanning the full registry by
            # owner string — the per-app Scheduler already holds its owned jobs (including waiting,
            # completed, and manual jobs that never touch the heap) in _jobs_by_name, and
            # remove_all_jobs() is the same identity-checked, registry-aware path the normal shutdown
            # uses (Scheduler.on_shutdown). A heap-only scan would miss those jobs and leak their
            # entity-watch subscriptions.
            #
            # Also deregisters the removal callback, mirroring on_shutdown()'s second statement —
            # remove_all_jobs() itself never does this (hassette/testing/_reset.py calls it on a
            # Scheduler instance meant to be reused across tests). An instance reaching this path is
            # discarded, not reused, so skipping the deregister would leak the stale callback (and the
            # Scheduler it closes over) in SchedulerService._removal_callbacks.
            await inst.scheduler.remove_all_jobs()
            inst.scheduler.scheduler_service.deregister_removal_callback(inst.scheduler.owner_id)
        except Exception:
            self.logger.warning("Job cleanup failed for instance '%s'", inst.app_config.instance_name, exc_info=True)

    async def shutdown_instance(
        self, inst: "App[AppConfig]", instance_index: int, *, deadline: float | None = None
    ) -> TeardownReport | None:
        """Stop a single app instance under its entry deadline.

        The stop leg gets ``entry_deadline_seconds`` from now, shortened to ``deadline`` when the caller
        has one (process exit passes what is left of its stop stage). When the deadline passes, this walks
        away: the instance is force-terminated and its listeners and jobs are removed by owner. A stop
        whose hook timed out, or that this walked away from, is reported FAILED with a "timed out" reason
        and an ``AppRegistry`` failure entry; any other completed stop is STOPPED.

        App identity is bound to the log context for the duration of the stop, so every record emitted
        during ``on_shutdown`` carries it.

        Returns:
            The instance's ``TeardownReport``, or ``None`` when its shutdown raised.
        """
        structlog.contextvars.bind_contextvars(
            app_key=inst.app_key,
            instance_name=inst.app_config.instance_name,
            instance_index=instance_index,
        )
        try:
            start_time = timer()
            entry_deadline = deadline_in(self.entry_deadline_seconds)
            stop_deadline = entry_deadline if deadline is None else min(entry_deadline, deadline)
            tighten_shutdown_deadline(inst, stop_deadline)
            task = create_lifecycle_task(inst.shutdown(), name=f"app:shutdown:{inst.unique_name}")
            timeout = max(0.0, stop_deadline - asyncio.get_running_loop().time())
            done, _pending = await asyncio.wait([task], timeout=timeout)
            walked_away = task not in done
            if walked_away:
                report = await self.walk_away_from_instance(inst, task)
            else:
                report = task.result()
            timed_out = walked_away or TeardownCause.SHUTDOWN_HOOK_TIMED_OUT in report.causes

            friendly_time = precisedelta(timer() - start_time, minimum_unit="milliseconds")
            if not timed_out:
                self.logger.debug(
                    "Stopped app '%s' '%s' in %s", inst.app_config.instance_name, inst.class_name, friendly_time
                )
                await self.emit_app_state_change(inst, status=STOPPED, previous_status=STOPPING)
                return report

            exc = TimeoutError(f"stop of app '{inst.app_config.instance_name}' timed out after {friendly_time}")
            if report.pending_tasks:
                left = f"still pending: {', '.join(report.pending_tasks)}"
            elif walked_away:
                left = f"force-terminated {inst.unique_name}; its evidence is incomplete, so work may still be running"
            else:
                left = "nothing still pending"
            self.logger.error(
                "Stop of app '%s' (%s) timed out after %s; %s",
                inst.app_config.instance_name,
                inst.class_name,
                friendly_time,
                left,
            )
            self.registry.record_failure(inst.app_key, instance_index, exc)
            await self.emit_app_state_change(inst, status=FAILED, previous_status=STOPPING, exception=exc)
            return report
        except Exception as exc:
            self.logger.error("Failed to stop app '%s':\n%s", inst.app_config.instance_name, get_short_traceback())
            await self.emit_app_state_change(inst, status=FAILED, previous_status=STOPPING, exception=exc)
            return None
        finally:
            structlog.contextvars.unbind_contextvars("app_key", "instance_name", "instance_index")

    async def walk_away_from_instance(
        self, inst: "App[AppConfig]", task: "asyncio.Task[TeardownReport]"
    ) -> TeardownReport:
        """Stop waiting on an instance whose stop outlived its entry deadline.

        Force-terminates it (which cancels its shutdown coordinator), removes its listeners and jobs by
        owner, and records it as force-terminated work for the process's hard exit. Returns the evidence
        force-termination left, which is incomplete (``FORCED_TERMINAL``).
        """
        inst._force_terminal()
        task.cancel()
        await self.remove_instance_registrations(inst)
        self.hassette.record_force_terminated([inst.unique_name])
        return inst.teardown_report or TeardownReport(causes=(TeardownCause.FORCED_TERMINAL,))

    async def shutdown_instances(
        self, instances: dict[int, "App[AppConfig]"], *, deadline: float | None = None
    ) -> TeardownReport:
        """Stop the given app instances concurrently, each under its own entry deadline.

        Args:
            instances: Dict of index -> App to shut down.
            deadline: An outer deadline each instance's stop is shortened to (process exit's stop stage).

        Returns:
            The instances' teardown reports, merged.
        """
        if not instances:
            return TeardownReport()

        self.logger.debug("Stopping %d app instances", len(instances))

        async def stop_one(idx: int, inst: "App[AppConfig]") -> TeardownReport | None:
            event = HassetteAppStateEvent.from_app(app=inst, status=STOPPING, previous_status=inst.status)
            await self.hassette.send_event(event)
            return await self.shutdown_instance(inst, idx, deadline=deadline)

        reports = await asyncio.gather(*(stop_one(idx, inst) for idx, inst in instances.items()))
        return merge_teardown_reports(*(report for report in reports if report is not None))

    async def shutdown_all(self, *, deadline: float | None = None) -> TeardownReport:
        """Stop every registered app instance concurrently, then clear the registry.

        Called from ``AppHandler``'s child stage at process exit, with what is left of its stop stage as
        ``deadline``, so no app's hooks are cut short by other apps' hooks.
        """
        self.logger.debug("Shutting down all apps")
        instances = [
            (idx, inst)
            for app_key in self.registry.app_keys()
            for idx, inst in self.registry.get_running_apps(app_key).items()
        ]
        reports = await asyncio.gather(
            *(self.shutdown_instances({idx: inst}, deadline=deadline) for idx, inst in instances)
        )
        self.registry.clear_all()
        return merge_teardown_reports(*reports) if reports else TeardownReport()

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
