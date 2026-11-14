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
    ActionOutcomes,
    failure_reason,
)
from hassette.events.hassette import HassetteAppStateEvent
from hassette.resources.lifecycle import create_lifecycle_task, mark_ready, skip_own_shutdown_hooks
from hassette.resources.shutdown_deadline import deadline_in, tighten_shutdown_deadline
from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult, incomplete_outcome, merge_outcomes
from hassette.schemas.app_snapshots import NeedsRestartInfo
from hassette.utils import date_utils
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
        instances: dict[str, "App[AppConfig]"],
        manifest: "AppManifest",
        instance_name: str | None = None,
        only_names: set[str] | None = None,
        *,
        outcomes: ActionOutcomes,
    ) -> None:
        """Initialize instances for an app key, recording each initialized instance's outcome.

        An instance whose initialization fails or times out is shut down under its entry deadline with its
        own shutdown hooks skipped, recorded FAILED, and flagged needs-restart if work may still be running
        (``shutdown_instance``). After all instances are initialized, awaits pending DB registrations and
        runs post-ready reconciliation to retire stale rows from previous sessions.

        Args:
            app_key: The app key
            instances: Dict of instance name -> App. Used for both the initialization loop (filtered
                by ``only_names`` when provided) and post-ready reconciliation (always uses
                the full dict so that pre-existing instances' listener/job rows are not retired).
            manifest: The app manifest
            instance_name: When provided, scopes post-ready reconciliation to this instance
                only, so restarting one instance does not retire sibling instances' rows.
                When None (default), reconciliation is app_key-scoped only — unchanged behavior.
            only_names: When provided, only instances with these names are initialized. Others are
                skipped but still included in reconciliation. Unrelated to ``instance_name``, which
                scopes the stored rows reconciliation may touch.
            outcomes: The request's outcomes; must target every initialized name.
        """
        class_name = manifest.class_name

        for name, inst in instances.items():
            if only_names is not None and name not in only_names:
                continue
            structlog.contextvars.bind_contextvars(
                app_key=app_key,
                instance_name=inst.instance_name,
            )
            try:
                await self.initialize_instance(inst, class_name, outcomes=outcomes)
            finally:
                structlog.contextvars.unbind_contextvars("app_key", "instance_name")

        # Post-ready reconciliation: retire stale rows from previous sessions.
        # Runs after the instance loop to ensure all registrations are complete.
        await self.reconcile_app_registrations(app_key, instances, instance_name=instance_name)

    async def initialize_instance(self, inst: "App[AppConfig]", class_name: str, *, outcomes: ActionOutcomes) -> None:
        """Initialize one instance, recording its outcome; on failure or timeout, shut it down as a failed init.

        STARTING is written and sent before the startup timeout opens, so a slow event send never counts
        against the app's startup budget. The ``try`` covers only the initialization itself. The RUNNING
        write follows it, and a failure to send its event is a telemetry failure, not an app failure: it is
        logged and the app keeps running.
        """
        await self.set_app_status(inst.app_key, inst.instance_name, STARTING)
        try:
            with anyio.fail_after(self.startup_timeout):
                await inst.initialize()
                mark_ready(inst, reason="initialized")
        except Exception as exc:
            self.logger.error(
                "Timed out while starting app '%s' (%s):\n%s"
                if isinstance(exc, TimeoutError)
                else "Failed to start app '%s' (%s):\n%s",
                inst.instance_name,
                class_name,
                get_short_traceback(-INIT_FAILURE_TRACEBACK_LIMIT),
            )
            skip_own_shutdown_hooks(inst)
            await self.shutdown_instance(inst, cause=exc, outcomes=outcomes)
            return

        self.logger.info("App '%s' (%s) initialized successfully", inst.instance_name, class_name)
        outcomes.succeeded(inst.instance_name)
        await self.set_app_status(inst.app_key, inst.instance_name, RUNNING)

    async def set_app_status(
        self,
        app_key: str,
        instance_name: str,
        to: ResourceStatus,
        *,
        app: "App[AppConfig] | None" = None,
        error: Exception | None = None,
        needs_restart: NeedsRestartInfo | None = None,
    ) -> None:
        """Write an app instance's status and send its event; the one path every lifecycle status write takes.

        The parameters are ``AppRegistry.set_status``'s, which decides whether the write is a change and may
        refuse it (an untracked or flagged name; see its docstring). No event is sent unless it changed
        something; a caller that needs to know whether a write landed checks the registry.

        A send failure is only logged: the event is telemetry, and the registry already holds the status, so
        failing to send must not turn a started app into a failed one or record a stop's failure twice.
        """
        change = self.registry.set_status(app_key, instance_name, to, app=app, error=error, needs_restart=needs_restart)
        if change is None:
            return
        try:
            await self.hassette.send_event(HassetteAppStateEvent.from_change(change))
        except Exception:
            self.logger.exception(
                "Failed to send the %s event for app '%s' (%s); its status is recorded",
                to,
                instance_name,
                change.class_name,
            )

    async def remove_instance_registrations(self, inst: "App[AppConfig]") -> None:
        """Remove an instance's bus listeners and scheduler jobs by owner, running no user hook.

        Used by an entry-deadline walk-away, which leaves an instance whose own ``Bus`` and ``Scheduler``
        teardown never finished, so nothing else would remove these.
        """
        try:
            inst.bus.remove_all_listeners()
        except Exception:
            self.logger.warning("Listener cleanup failed for instance '%s'", inst.instance_name, exc_info=True)
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
            self.logger.warning("Job cleanup failed for instance '%s'", inst.instance_name, exc_info=True)

    async def shutdown_instance(
        self,
        inst: "App[AppConfig]",
        *,
        deadline: float | None = None,
        cause: Exception | None = None,
        outcomes: ActionOutcomes,
    ) -> ShutdownOutcome | None:
        """Shut down a single app instance under its entry deadline and record the outcome.

        The teardown gets ``entry_deadline_seconds`` from now, shortened to ``deadline`` when the caller
        has one (process exit passes what is left of its stop stage). When the deadline passes, this walks
        away: the instance is force-terminated and its listeners and jobs are removed by owner.

        The instance stays registered until its teardown has finished, so readers see its own STOPPING
        rather than a STOPPED placeholder. The outcome's status write then replaces the live entry directly:
        FAILED drops the ``App`` reference, and STOPPED removes the entry.

        Outcomes:

        - ``cause`` given (a failed init, or a failure after registration): FAILED with ``cause`` recorded,
          over whatever status the entry holds (STARTING for a failed init), since no STOPPING was written.
        - A stop whose outcome says work may still be running (``ShutdownOutcome.is_restart_safe`` is
          ``False``: a walk-away, pending tasks, a raised shutdown): FAILED, a failure entry, and one ERROR
          naming what is left and saying to restart hassette. It is worded "timed out" for a walk-away, or
          when the outcome's result is ``TIMED_OUT``; an ``INCOMPLETE`` outcome is worded "stopped, but…"
          even when a hook also timed out.
        - A stop whose hook timed out but left nothing running: FAILED with a "timed out" reason; reloadable.
        - Any other stop: STOPPED.

        In every FAILED outcome, an instance whose work may still run is flagged needs-restart as part of the
        FAILED write. The first flag on a name stands until restart.

        Each outcome is also recorded in ``outcomes``: ``succeeded`` for a clean stop, ``failed`` otherwise
        (with ``needs_restart`` when this stop flagged the instance), and ``refused`` when the instance was
        already flagged by something else, such as process exit.

        The caller sets ``skip_own_shutdown_hooks`` beforehand when the app's own hooks must not run.
        App identity is bound to the log context for the duration of the stop, so every record emitted
        during ``on_shutdown`` carries it.

        Returns:
            The instance's ``ShutdownOutcome``, or ``None`` when its shutdown raised.
        """
        structlog.contextvars.bind_contextvars(
            app_key=inst.app_key,
            instance_name=inst.instance_name,
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
                outcome = await self.walk_away_from_instance(inst, task) if force_terminated else task.result()
            except Exception as exc:
                failure = cause or exc
                await self.settle_raised_shutdown(inst, failure, outcomes=outcomes)
                return None

            friendly_time = precisedelta(timer() - start_time, minimum_unit="milliseconds")

            if cause is not None:
                await self.settle_failed_init(
                    inst,
                    cause,
                    outcome,
                    friendly_time=friendly_time,
                    outcomes=outcomes,
                )
                return outcome

            timed_out = force_terminated or outcome.result is ShutdownResult.TIMED_OUT
            if outcome.is_restart_safe and not timed_out:
                self.logger.info("Stopped app '%s' '%s' in %s", inst.instance_name, inst.class_name, friendly_time)
                outcomes.succeeded(inst.instance_name)
                await self.set_app_status(inst.app_key, inst.instance_name, STOPPED)
                return outcome

            await self.settle_failed_stop(
                inst,
                outcome,
                timed_out=timed_out,
                friendly_time=friendly_time,
                outcomes=outcomes,
            )
            return outcome
        finally:
            structlog.contextvars.unbind_contextvars("app_key", "instance_name")
            # An instance no longer registered (its entry FAILED or removed) is out of reach of ``off``, yet its
            # loggers are process-global and keyed by name, so return them to config here, even when its teardown
            # left work running. The registry's capture pair stays, so the next instance under this name starts
            # captured. A stop cancelled before its status write leaves the instance registered, and ``off`` still
            # reaches it.
            if inst.debug_capture and self.registry.get(inst.app_key, inst.instance_name) is not inst:
                inst.set_debug_capture(False)

    async def settle_raised_shutdown(
        self,
        inst: "App[AppConfig]",
        failure: Exception,
        *,
        outcomes: ActionOutcomes,
    ) -> None:
        """Settle a teardown that raised: FAILED with ``failure``, flagged unless its stored outcome is safe.

        The coordinator stores an ``INCOMPLETE`` outcome before re-raising, so this is normally a
        needs-restart outcome too; with no outcome at all, nothing proves the instance's work ended.
        """
        name = inst.instance_name
        self.logger.error("Failed to stop app '%s':\n%s", name, get_short_traceback())
        stored = inst.shutdown_outcome
        if stored is None or not stored.is_restart_safe:
            left = describe_left_running(stored or ShutdownOutcome())
            await self.fail_needs_restart(
                inst,
                failure,
                flag_reason=f"shutdown raised; {left}",
                shutdown_outcome=stored,
                outcome_reason=failure_reason(failure),
                outcomes=outcomes,
            )
        else:
            await self.set_app_status(inst.app_key, name, FAILED, error=failure)
            outcomes.failed(name, failure_reason(failure))

    async def settle_failed_init(
        self,
        inst: "App[AppConfig]",
        cause: Exception,
        outcome: ShutdownOutcome,
        *,
        friendly_time: str,
        outcomes: ActionOutcomes,
    ) -> None:
        """Settle a failed init's outcome: the failure entry, and a needs-restart flag if work may still run.

        The FAILED write replaces the instance's STARTING entry. The init failure itself was already logged at
        ERROR by its caller; a needs-restart flag gets its own ERROR.
        """
        if outcome.is_restart_safe:
            await self.set_app_status(inst.app_key, inst.instance_name, FAILED, error=cause)
            self.logger.info(
                "Shut down app '%s' (%s) after its failed start in %s",
                inst.instance_name,
                inst.class_name,
                friendly_time,
            )
            outcomes.failed(inst.instance_name, failure_reason(cause))
            return
        left = describe_left_running(outcome)
        await self.fail_needs_restart(
            inst,
            cause,
            flag_reason=f"failed to start, and {left}",
            shutdown_outcome=outcome,
            outcome_reason=failure_reason(cause),
            outcomes=outcomes,
        )

    async def settle_failed_stop(
        self,
        inst: "App[AppConfig]",
        outcome: ShutdownOutcome,
        *,
        timed_out: bool,
        friendly_time: str,
        outcomes: ActionOutcomes,
    ) -> None:
        """Settle a stop that timed out or left work running: one ERROR, a FAILED write, and maybe a flag.

        Called only for a stop that timed out, left work running, or both; a clean stop that didn't time
        out is STOPPED and never reaches here.
        """
        name = inst.instance_name
        if outcome.is_restart_safe:
            # Restart-safe here means the stop timed out (see above) but nothing is still pending.
            exc: Exception = TimeoutError(f"stop of app '{name}' timed out after {friendly_time}")
            self.logger.error(
                "Stop of app '%s' (%s) timed out after %s; nothing still pending", name, inst.class_name, friendly_time
            )
            await self.set_app_status(inst.app_key, name, FAILED, error=exc)
            outcomes.failed(name, str(exc))
            return

        left = describe_left_running(outcome)
        if timed_out:
            reason = f"stop timed out after {friendly_time}; {left}"
            exc = TimeoutError(f"stop of app '{name}' timed out after {friendly_time}; {left}")
        else:
            reason = f"stopped, but {left}"
            exc = RuntimeError(f"app '{name}' stopped, but {left}")
        await self.fail_needs_restart(
            inst, exc, flag_reason=reason, shutdown_outcome=outcome, outcome_reason=str(exc), outcomes=outcomes
        )

    async def fail_needs_restart(
        self,
        inst: "App[AppConfig]",
        error: Exception,
        *,
        flag_reason: str,
        shutdown_outcome: ShutdownOutcome | None,
        outcome_reason: str,
        outcomes: ActionOutcomes,
    ) -> None:
        """Log the needs-restart ERROR, write FAILED with the flag, and record the outcome.

        ``flag_reason`` is the flag's text, shown in the ERROR log and in every later refusal of this name.
        ``outcome_reason`` is what ``outcomes`` records for this action, usually the error itself.

        Whether this write flags the name is read before it: the first flag on a name stands, so a name
        already flagged (process exit's teardown takes no app-key lock) reports the earlier flag as a refusal.
        """
        newly_flagged = self.registry.get_needs_restart(inst.app_key, inst.instance_name) is None
        self.logger.error(
            "App '%s' (%s) %s; restart hassette to recover", inst.instance_name, inst.class_name, flag_reason
        )
        flag = NeedsRestartInfo(
            reason=flag_reason,
            pending_tasks=tuple(shutdown_outcome.still_running) if shutdown_outcome is not None else (),
            flagged_at=date_utils.now(),
        )
        await self.set_app_status(inst.app_key, inst.instance_name, FAILED, error=error, needs_restart=flag)
        self.record_flagged_outcome(outcomes, inst, outcome_reason, newly_flagged)

    def record_flagged_outcome(
        self, outcomes: ActionOutcomes, inst: "App[AppConfig]", failure: str, newly_flagged: bool
    ) -> None:
        """Record the outcome of a failure that leaves the instance flagged needs-restart.

        ``failed`` with ``needs_restart`` when this action flagged it. When something else flagged it first
        (process exit's teardown takes no app-key lock), the instance reports the earlier flag as a refusal.
        """
        refusal = None if newly_flagged else self.registry.refusal_reason(inst.app_key, inst.instance_name)
        if refusal is None:
            outcomes.failed(inst.instance_name, failure, needs_restart=True)
        else:
            outcomes.refused(inst.instance_name, refusal)

    async def walk_away_from_instance(
        self, inst: "App[AppConfig]", task: "asyncio.Task[ShutdownOutcome]"
    ) -> ShutdownOutcome:
        """Stop waiting on an instance whose stop outlived its entry deadline.

        Force-terminates it (which cancels its shutdown coordinator) and removes its listeners and jobs by
        owner (bounded by ``WALK_AWAY_CLEANUP_TIMEOUT_SECONDS``). Returns the outcome force-termination
        left, which is ``INCOMPLETE``.
        """
        inst._force_terminal()
        task.cancel()
        try:
            with anyio.fail_after(WALK_AWAY_CLEANUP_TIMEOUT_SECONDS):
                await self.remove_instance_registrations(inst)
        except TimeoutError:
            self.logger.warning(
                "Cleanup timed out for walked-away instance '%s' — some listeners or jobs may leak until restart",
                inst.instance_name,
            )
        return inst.shutdown_outcome or incomplete_outcome(f"{inst.unique_name} was force-terminated")

    async def shutdown_instances(
        self, instances: Iterable["App[AppConfig]"], *, deadline: float | None = None, outcomes: ActionOutcomes
    ) -> ShutdownOutcome:
        """Stop the given app instances concurrently, each under its own entry deadline.

        Args:
            instances: The apps to shut down.
            deadline: An outer deadline each instance's stop is shortened to (process exit's stop stage).
            outcomes: The request's outcomes; each instance records its own before returning, so one
                that raises can't erase a sibling's.

        Returns:
            The instances' shutdown outcomes, merged.
        """
        instances = list(instances)
        if not instances:
            return ShutdownOutcome()

        self.logger.debug("Stopping %d app instances", len(instances))

        async def stop_one(inst: "App[AppConfig]") -> ShutdownOutcome | None:
            await self.set_app_status(inst.app_key, inst.instance_name, STOPPING)
            return await self.shutdown_instance(inst, deadline=deadline, outcomes=outcomes)

        results = await gather_all((stop_one(inst) for inst in instances), name="app:stop_instance")
        return merge_outcomes(*(outcome for outcome in results if outcome is not None))

    async def shutdown_all(self, *, deadline: float | None = None) -> ShutdownOutcome:
        """Stop every registered app instance concurrently, then clear the registry.

        Called from ``AppHandler``'s child stage at process exit, with what is left of its stop stage as
        ``deadline``, so no app's hooks are cut short by other apps' hooks. ``AppSync`` hooks share the
        sync executor's threads, so past its worker count the wait for a thread counts against their bound.

        A runtime stop already in flight is still registered (``shutdown_instance`` writes STOPPED after the
        teardown), so it is reached here too: this joins its single shielded shutdown attempt under the
        tighter deadline, and both owners handle the outcome.
        """
        self.logger.debug("Shutting down all apps")
        instances = [
            inst for app_key in self.registry.app_keys() for inst in self.registry.get_live_apps(app_key).values()
        ]
        # Process exit has no response to carry outcomes; each stop gets its own, which nothing reads.
        results = await gather_all(
            (
                self.shutdown_instances(
                    [inst],
                    deadline=deadline,
                    outcomes=ActionOutcomes([inst.instance_name]),
                )
                for inst in instances
            ),
            name="app:shutdown_all",
        )
        # A raw reset that sends no events; ``AppRegistry.clear_all`` says why.
        self.registry.clear_all()
        return merge_outcomes(*results)


def describe_left_running(outcome: ShutdownOutcome) -> str:
    """Say what a restart-unsafe teardown may have left running, for a needs-restart ERROR and reason.

    Any result can reach here, since a restart-unsafe outcome is one with tasks still running. Its reason,
    when set, comes first and names the resource and step behind it: a walk-away's forced terminal state,
    or the hook that timed out or raised. Without a reason, only the running work is described.
    """
    if outcome.still_running:
        running = f"work is still running: {', '.join(outcome.still_running)}"
    else:
        running = "work may still be running"
    if outcome.reason:
        return f"{outcome.reason}; {running}"
    return running


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
