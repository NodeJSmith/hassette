"""AppInstanceLifecycleMixin — per-instance initialization, shutdown, needs-restart flagging, and state events."""

import asyncio
import typing
from collections.abc import Awaitable, Callable, Coroutine, Iterable
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
from hassette.resources.lifecycle import create_lifecycle_task, mark_ready, skip_own_shutdown_hooks
from hassette.resources.shutdown_deadline import deadline_in, tighten_shutdown_deadline
from hassette.resources.teardown import TeardownCause, TeardownReport, merge_teardown_reports
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app.app import App
    from hassette.config.classes import AppManifest
    from hassette.core.app_registry import AppRegistry

T = typing.TypeVar("T")

WALK_AWAY_CLEANUP_TIMEOUT_SECONDS = 5.0
"""Bound on removing a walked-away instance's listeners and jobs, so a wedged database worker can't hold the
app-key lock. A fixed framework cap, like the drain cap and the executor join."""


class AppInstanceLifecycleMixin:
    """Per-instance initialization, shutdown, needs-restart flagging, and state events for ``AppLifecycleService``."""

    # Provided by the AppLifecycleService host (its own body, Resource, or a sibling mixin);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    registry: "AppRegistry"
    startup_timeout: int
    entry_deadline_seconds: float
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

        An instance whose initialization fails or times out is shut down under its entry deadline with its
        own shutdown hooks skipped, recorded FAILED, and flagged needs-restart if work may still be running
        (``shutdown_instance``). After all instances are initialized, awaits pending DB registrations and
        runs post-ready reconciliation to retire stale rows from previous sessions.

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
                await self.initialize_instance(inst, idx, class_name)
            finally:
                structlog.contextvars.unbind_contextvars("app_key", "instance_name", "instance_index")

        # Post-ready reconciliation: retire stale rows from previous sessions.
        # Runs after the instance loop to ensure all registrations are complete.
        await self.reconcile_app_registrations(app_key, instances, instance_index=instance_index)

    async def initialize_instance(self, inst: "App[AppConfig]", index: int, class_name: str) -> None:
        """Initialize one instance; on failure or timeout, shut it down as a failed init.

        The ``try`` covers only the initialization itself. The RUNNING event is sent after it, and a failure
        to send it is a telemetry failure, not an app failure: it is logged and the app keeps running.
        """
        try:
            with anyio.fail_after(self.startup_timeout):
                await inst.initialize()
                mark_ready(inst, reason="initialized")
        except TimeoutError as exc:
            self.logger.error(
                "Timed out while starting app '%s' (%s):\n%s",
                inst.app_config.instance_name,
                class_name,
                get_short_traceback(-INIT_FAILURE_TRACEBACK_LIMIT),
            )
            skip_own_shutdown_hooks(inst)
            await self.shutdown_instance(inst, index, cause=exc)
            return
        except Exception as exc:
            self.logger.error(
                "Failed to start app '%s' (%s):\n%s",
                inst.app_config.instance_name,
                class_name,
                get_short_traceback(-INIT_FAILURE_TRACEBACK_LIMIT),
            )
            skip_own_shutdown_hooks(inst)
            await self.shutdown_instance(inst, index, cause=exc)
            return

        self.logger.debug("App '%s' (%s) initialized successfully", inst.app_config.instance_name, class_name)
        await self.send_outcome_event(inst, status=RUNNING, previous_status=STARTING)

    async def send_outcome_event(
        self,
        inst: "App[AppConfig]",
        *,
        status: ResourceStatus,
        previous_status: ResourceStatus,
        exception: BaseException | None = None,
    ) -> None:
        """Send the status event for an outcome that is already recorded; a send failure is only logged.

        The event is telemetry: the registry already holds the outcome, so failing to send it must not
        turn a started app into a failed one or record a stop's failure twice.
        """
        try:
            await self.emit_app_state_change(inst, status=status, previous_status=previous_status, exception=exception)
        except Exception:
            self.logger.exception(
                "Failed to send the %s event for app '%s' (%s); its outcome is recorded",
                status,
                inst.app_config.instance_name,
                inst.class_name,
            )

    async def remove_instance_registrations(self, inst: "App[AppConfig]") -> None:
        """Remove an instance's bus listeners and scheduler jobs by owner, running no user hook.

        Used by an entry-deadline walk-away, which leaves an instance whose own ``Bus`` and ``Scheduler``
        teardown never finished, so nothing else would remove these.
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
        self,
        inst: "App[AppConfig]",
        instance_index: int,
        *,
        deadline: float | None = None,
        cause: Exception | None = None,
    ) -> TeardownReport | None:
        """Shut down a single app instance under its entry deadline and record the outcome.

        The teardown gets ``entry_deadline_seconds`` from now, shortened to ``deadline`` when the caller
        has one (process exit passes what is left of its stop stage). When the deadline passes, this walks
        away: the instance is force-terminated and its listeners and jobs are removed by owner.

        The instance stays registered until its teardown has finished, so readers see its own STOPPING
        rather than a STOPPED placeholder. It is unregistered after that and before the outcome is
        recorded, because recording a failure writes the entry an earlier unregister would discard.

        Outcomes:

        - ``cause`` given (a failed init, or a failure after registration): FAILED with ``cause`` recorded,
          ``previous_status`` STARTING, since no STOPPING event was sent.
        - A stop whose report says work may still be running (``TeardownReport.is_restart_safe`` is
          ``False``: a walk-away, pending tasks, a raised shutdown): FAILED, a failure entry, and one ERROR
          naming what is left and saying to restart hassette.
        - A stop whose hook timed out but left nothing running: FAILED with a "timed out" reason; reloadable.
        - Any other stop: STOPPED.

        In every FAILED outcome, an instance whose work may still run is flagged needs-restart in
        ``AppRegistry`` before the event is sent. The first flag at an index stands until restart.

        The caller sets ``skip_own_shutdown_hooks`` beforehand when the app's own hooks must not run.
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
            force_terminated = False
            try:
                entry_deadline = deadline_in(self.entry_deadline_seconds)
                stop_deadline = entry_deadline if deadline is None else min(entry_deadline, deadline)
                tighten_shutdown_deadline(inst, stop_deadline)
                task = create_lifecycle_task(inst.shutdown(), name=f"app:shutdown:{inst.unique_name}")
                timeout = max(0.0, stop_deadline - asyncio.get_running_loop().time())
                done, _pending = await asyncio.wait([task], timeout=timeout)
                force_terminated = task not in done
                report = await self.walk_away_from_instance(inst, task) if force_terminated else task.result()
            except Exception as exc:
                failure = cause or exc
                await self.settle_raised_shutdown(inst, instance_index, failure, cause is not None, force_terminated)
                return None

            self.registry.unregister_app(inst.app_key, instance_index)
            friendly_time = precisedelta(timer() - start_time, minimum_unit="milliseconds")

            if cause is not None:
                self.settle_failed_init(inst, instance_index, cause, report, force_terminated, friendly_time)
                await self.send_outcome_event(inst, status=FAILED, previous_status=STARTING, exception=cause)
                return report

            timed_out = force_terminated or TeardownCause.SHUTDOWN_HOOK_TIMED_OUT in report.causes
            if report.is_restart_safe and not timed_out:
                self.logger.debug(
                    "Stopped app '%s' '%s' in %s", inst.app_config.instance_name, inst.class_name, friendly_time
                )
                await self.send_outcome_event(inst, status=STOPPED, previous_status=STOPPING)
                return report

            exc = self.settle_failed_stop(inst, instance_index, report, timed_out, force_terminated, friendly_time)
            await self.send_outcome_event(inst, status=FAILED, previous_status=STOPPING, exception=exc)
            return report
        finally:
            structlog.contextvars.unbind_contextvars("app_key", "instance_name", "instance_index")

    async def settle_raised_shutdown(
        self,
        inst: "App[AppConfig]",
        instance_index: int,
        failure: Exception,
        is_init_failure: bool,
        force_terminated: bool,
    ) -> None:
        """Settle a teardown that raised: FAILED with ``failure``, flagged unless its stored report is safe.

        The coordinator stores a COORDINATOR_FAILED report before re-raising, so this is normally a
        needs-restart outcome too; with no report at all, nothing proves the instance's work ended.
        """
        name = inst.app_config.instance_name
        self.logger.error("Failed to stop app '%s':\n%s", name, get_short_traceback())
        self.registry.unregister_app(inst.app_key, instance_index)
        self.registry.record_failure(inst.app_key, instance_index, failure)
        report = inst.teardown_report
        if report is None or not report.is_restart_safe:
            left = describe_left_running(report or TeardownReport(), inst, force_terminated=force_terminated)
            reason = f"shutdown raised; {left}"
            self.logger.error("App '%s' (%s) %s; restart hassette to recover", name, inst.class_name, reason)
            self.flag_instance_needs_restart(inst, instance_index, reason, report)
        previous = STARTING if is_init_failure else STOPPING
        await self.send_outcome_event(inst, status=FAILED, previous_status=previous, exception=failure)

    def settle_failed_init(
        self,
        inst: "App[AppConfig]",
        instance_index: int,
        cause: Exception,
        report: TeardownReport,
        force_terminated: bool,
        friendly_time: str,
    ) -> None:
        """Settle a failed init's outcome: the failure entry, and a needs-restart flag if work may still run.

        Runs synchronously right after the unregister. The init failure itself was already logged at
        ERROR by its caller; a needs-restart flag gets its own ERROR.
        """
        self.registry.record_failure(inst.app_key, instance_index, cause)
        if report.is_restart_safe:
            self.logger.debug(
                "Shut down app '%s' (%s) after its failed start in %s",
                inst.app_config.instance_name,
                inst.class_name,
                friendly_time,
            )
            return
        left = describe_left_running(report, inst, force_terminated=force_terminated)
        reason = f"failed to start, and {left}"
        self.logger.error(
            "App '%s' (%s) %s; restart hassette to recover", inst.app_config.instance_name, inst.class_name, reason
        )
        self.flag_instance_needs_restart(inst, instance_index, reason, report)

    def settle_failed_stop(
        self,
        inst: "App[AppConfig]",
        instance_index: int,
        report: TeardownReport,
        timed_out: bool,
        force_terminated: bool,
        friendly_time: str,
    ) -> Exception:
        """Settle a stop that timed out or left work running: one ERROR, a failure entry, and maybe a flag.

        Called only for a stop that timed out, left work running, or both; a clean stop that didn't time
        out is STOPPED and never reaches here.

        Returns:
            The exception recorded as the instance's failure.
        """
        name = inst.app_config.instance_name
        if report.is_restart_safe:
            # Restart-safe here means the stop timed out (see above) but nothing is still pending.
            exc: Exception = TimeoutError(f"stop of app '{name}' timed out after {friendly_time}")
            self.logger.error(
                "Stop of app '%s' (%s) timed out after %s; nothing still pending", name, inst.class_name, friendly_time
            )
            self.registry.record_failure(inst.app_key, instance_index, exc)
            return exc

        left = describe_left_running(report, inst, force_terminated=force_terminated)
        if timed_out:
            reason = f"stop timed out after {friendly_time}; {left}"
            exc = TimeoutError(f"stop of app '{name}' timed out after {friendly_time}; {left}")
        else:
            reason = f"stopped, but {left}"
            exc = RuntimeError(f"app '{name}' stopped, but {left}")
        self.logger.error("App '%s' (%s) %s; restart hassette to recover", name, inst.class_name, reason)
        self.registry.record_failure(inst.app_key, instance_index, exc)
        self.flag_instance_needs_restart(inst, instance_index, reason, report)
        return exc

    def flag_instance_needs_restart(
        self, inst: "App[AppConfig]", instance_index: int, reason: str, report: TeardownReport | None
    ) -> None:
        """Write the instance's needs-restart record; the first record at an index stands."""
        self.registry.flag_needs_restart(
            inst.app_key,
            instance_index,
            instance_name=inst.app_config.instance_name,
            class_name=inst.class_name,
            reason=reason,
            pending_tasks=report.pending_tasks if report is not None else (),
        )

    async def walk_away_from_instance(
        self, inst: "App[AppConfig]", task: "asyncio.Task[TeardownReport]"
    ) -> TeardownReport:
        """Stop waiting on an instance whose stop outlived its entry deadline.

        Force-terminates it (which cancels its shutdown coordinator), removes its listeners and jobs by
        owner (bounded by ``WALK_AWAY_CLEANUP_TIMEOUT_SECONDS``), and records it as force-terminated
        work for the process's hard exit. Returns the evidence force-termination left, which is incomplete
        (``FORCED_TERMINAL``).
        """
        inst._force_terminal()
        task.cancel()
        try:
            with anyio.fail_after(WALK_AWAY_CLEANUP_TIMEOUT_SECONDS):
                await self.remove_instance_registrations(inst)
        except TimeoutError:
            self.logger.warning(
                "Cleanup timed out for walked-away instance '%s' — some listeners or jobs may leak until restart",
                inst.app_config.instance_name,
            )
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

        reports = await gather_all((stop_one(idx, inst) for idx, inst in instances.items()), name="app:stop_instance")
        return merge_teardown_reports(*(report for report in reports if report is not None))

    async def shutdown_all(self, *, deadline: float | None = None) -> TeardownReport:
        """Stop every registered app instance concurrently, then clear the registry.

        Called from ``AppHandler``'s child stage at process exit, with what is left of its stop stage as
        ``deadline``, so no app's hooks are cut short by other apps' hooks. ``AppSync`` hooks share the
        sync executor's threads, so past its worker count the wait for a thread counts against their bound.

        A runtime stop already in flight is still registered (``shutdown_instance`` unregisters after the
        teardown), so it is reached here too: this joins its single shielded shutdown attempt under the
        tighter deadline, and both owners handle the report.
        """
        self.logger.debug("Shutting down all apps")
        instances = [
            (idx, inst)
            for app_key in self.registry.app_keys()
            for idx, inst in self.registry.get_running_apps(app_key).items()
        ]
        reports = await gather_all(
            (self.shutdown_instances({idx: inst}, deadline=deadline) for idx, inst in instances),
            name="app:shutdown_all",
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


def describe_left_running(report: TeardownReport, inst: "App[AppConfig]", *, force_terminated: bool) -> str:
    """Say what a restart-unsafe teardown may have left running, for a needs-restart ERROR and reason."""
    if report.pending_tasks:
        return f"work is still running: {', '.join(report.pending_tasks)}"
    if force_terminated:
        return f"{inst.unique_name} was force-terminated; its evidence is incomplete, so work may still be running"
    return "its teardown evidence is incomplete, so work may still be running"


async def gather_all(coros: Iterable[Coroutine[typing.Any, typing.Any, T]], *, name: str) -> list[T]:
    """Run every coroutine to the end, then re-raise the first exception any of them raised.

    Unlike a plain ``asyncio.gather``, no coroutine is left running detached after another one raised.
    Each runs in a ``create_lifecycle_task()`` task: at exit the root's TaskBucket is sealed and is the
    loop's task-factory fallback, so the tasks ``asyncio.gather`` would create itself are rejected.
    """
    tasks = [create_lifecycle_task(coro, name=name) for coro in coros]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return typing.cast("list[T]", results)
