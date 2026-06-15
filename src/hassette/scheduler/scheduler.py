"""
Scheduler for running tasks at specific times or intervals with flexible triggers.

The Scheduler provides intuitive methods for scheduling one-time and recurring tasks using
trigger objects, simple time delays, cron expressions, or daily wall-clock times. Jobs are
automatically cleaned up when the app shuts down, and support both async and sync callables.

Scheduling methods (``add_job``, ``schedule``, ``run_in``, ``run_every``, ``run_daily``, etc.)
return a ``Coroutine`` and must be awaited. Registration completes inline: ``job.db_id`` is a
valid integer immediately when the awaited call returns.

Examples:
    One-time delayed execution::

        # Run in 30 seconds
        await self.scheduler.run_in(self.cleanup_task, 30)

        # Run once at 7:00 AM today (or tomorrow if 07:00 has already passed)
        await self.scheduler.run_once(self.morning_routine, at="07:00")

    Recurring execution::

        # Every 5 minutes
        await self.scheduler.run_every(self.check_sensors, minutes=5)

        # Every hour
        await self.scheduler.run_hourly(self.log_status)

        # Every day at 6:30 AM (wall-clock anchored, DST-safe)
        await self.scheduler.run_daily(self.morning_routine, at="06:30")

        # Every 5 minutes
        await self.scheduler.run_minutely(self.quick_check, minutes=5)

    Cron-style scheduling::

        # Weekdays at 9 AM
        await self.scheduler.run_cron(self.workday_routine, "0 9 * * 1-5")

    Job groups::

        # Schedule multiple jobs in a named group for bulk cancellation
        await self.scheduler.run_daily(self.open_blinds, at="08:00", group="morning")
        await self.scheduler.run_daily(self.play_music, at="08:05", group="morning")

        # Cancel all jobs in the group
        self.scheduler.cancel_group("morning")

    Using the primary entry point directly::

        from hassette.scheduler import Every, Daily, Cron

        job = await self.scheduler.schedule(self.my_func, Every(hours=1))
        job = await self.scheduler.schedule(self.my_func, Daily(at="07:00"), group="morning")
        job = await self.scheduler.schedule(self.my_func, Cron("0 9 * * 1-5"))

    Job management::

        # Named job for easier management
        job = await self.scheduler.run_daily(self.backup_data, at="02:00", name="daily_backup")

        # Cancel a specific job
        job.cancel()
"""

import asyncio
import typing
from collections.abc import Coroutine, Mapping
from typing import Any, Literal

from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.core.await_guard import guard_await
from hassette.core.scheduler_service import SchedulerService
from hassette.resources.base import Resource
from hassette.types import TriggerProtocol
from hassette.types.enums import ExecutionMode
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.source_capture import capture_registration_source

from .classes import ScheduledJob
from .sync import SchedulerSyncFacade
from .triggers import After, Cron, Daily, Every, Once

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.types import JobCallable
    from hassette.types.types import SchedulerErrorHandlerType


class Scheduler(Resource):
    """Scheduler resource for managing scheduled jobs."""

    scheduler_service: SchedulerService
    """The scheduler service instance."""

    sync: SchedulerSyncFacade
    """Synchronous facade for scheduling jobs from sync code (e.g. ``AppSync`` hooks)."""

    _jobs_by_name: dict[str, "ScheduledJob"]
    """Tracks jobs by name for uniqueness validation within this scheduler instance."""

    _jobs_by_group: dict[str, set["ScheduledJob"]]
    """Tracks jobs by group for bulk cancellation.

    Uses ``set`` for O(1) membership test and discard. ``ScheduledJob.__hash__``
    is based on ``job_id``, which is unique and immutable after construction.
    """

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        assert self.parent is not None, (
            "Scheduler requires a parent Resource for telemetry identity (app_key/source_tier)"
        )
        assert self.hassette._scheduler_service is not None, "Scheduler service not initialized"
        self.scheduler_service = self.hassette._scheduler_service
        self._jobs_by_name = {}
        self._jobs_by_group: dict[str, set[ScheduledJob]] = {}
        self._error_handler: SchedulerErrorHandlerType | None = None
        self.sync = self.add_child(SchedulerSyncFacade, scheduler=self)

        # Register removal callback so exhausted one-shot jobs are removed from _jobs_by_group
        # automatically when SchedulerService removes them after firing.
        self.scheduler_service.register_removal_callback(self.owner_id, self._on_job_removed)

    def _on_job_removed(self, job: "ScheduledJob") -> None:
        """Callback invoked by SchedulerService when a job is auto-exhausted.

        Keeps _jobs_by_group and _jobs_by_name in sync when SchedulerService removes a
        one-shot job after it fires or when a job is dequeued via cancel_job.
        """
        self._jobs_by_name.pop(job.name, None)
        if job.group is not None:
            group_set = self._jobs_by_group.get(job.group)
            if group_set is not None:
                group_set.discard(job)
                if not group_set:
                    del self._jobs_by_group[job.group]

    async def on_initialize(self) -> None:
        self._error_handler = None
        self.mark_ready(reason="Scheduler initialized")

    async def on_shutdown(self) -> None:
        await self._remove_all_jobs()
        self.scheduler_service.deregister_removal_callback(self.owner_id)

    def on_error(self, handler: "SchedulerErrorHandlerType") -> None:
        """Register an app-level error handler for this scheduler.

        The handler is called when any job on this scheduler raises an exception
        (including ``TimeoutError``) and the job does not have its own
        per-registration error handler.

        This is an app-level fallback — it is resolved at dispatch time, not at job
        registration time. A later call to ``on_error()`` replaces any previously
        registered handler.

        Note: error handlers are spawned as fire-and-forget tasks. Handlers spawned near
        app shutdown may be cancelled before they complete. Do not rely on error handlers
        for delivery-critical alerting during system teardown.

        Args:
            handler: A sync or async callable that accepts a
                :class:`~hassette.scheduler.error_context.SchedulerErrorContext`.
        """
        self._error_handler = handler

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.logging.scheduler_service

    def add_job(
        self, job: "ScheduledJob", *, if_exists: Literal["error", "skip", "replace"] = "error"
    ) -> "Coroutine[Any, Any, ScheduledJob]":
        """Add a job to the scheduler.

        Must be awaited. Scheduling completes before the call returns.
        ``job.db_id`` is a valid integer immediately on return.

        DB registration is awaited inline — ``job.db_id`` is set before this
        method returns, eliminating the window where a job fires with
        ``db_id=None``.

        Args:
            job: The job to add.
            if_exists: Behavior when a job with the same name already exists.
                ``"error"`` (default) raises ``ValueError``.
                ``"skip"`` returns the existing job if it matches; raises
                ``ValueError`` if the name matches but the configuration differs.
                ``"replace"`` cancels the existing job (recording it as cancelled
                in telemetry) and registers the new job in its place.

        Returns:
            The added job, or the existing job when ``if_exists="skip"`` and a
            matching job is already registered. ``job.db_id`` is a valid
            integer immediately on return.

        Raises:
            TypeError: If job is not a ScheduledJob.
            ValueError: If a job with the same name already exists and either
                ``if_exists="error"`` or the existing job's configuration differs.
        """
        # Synchronous validation runs before the handle is constructed (design Edge Cases).
        if not isinstance(job, ScheduledJob):
            raise TypeError(f"Expected ScheduledJob, got {type(job).__name__}")
        # Eager capture in the public def — user frame is live here (not inside the async body).
        # Returns a 2-tuple — unpack it. Two destinations: guard_await (warning attribution) AND
        # _add_job (backfills job.source_location / registration_source for telemetry when empty).
        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/core/await_guard.py / design/071.
        return guard_await(
            self._add_job(
                job,
                if_exists=if_exists,
                source_location=source_location,
                registration_source=registration_source or "",
            ),
            owner=self.parent,
            source_location=source_location,
            method_name="add_job",
        )

    async def _add_job(
        self,
        job: "ScheduledJob",
        *,
        if_exists: Literal["error", "skip", "replace"] = "error",
        source_location: str = "",
        registration_source: str = "",
    ) -> "ScheduledJob":
        """Async body for add_job: duplicate-name check + registry mutations + DB registration.

        Duplicate-name handling and registry mutations must not run for a never-awaited
        call — they would pollute _jobs_by_name/_jobs_by_group. Matches the bus
        _resolve_and_register split where collision check lives in the awaited coroutine.

        source_location and registration_source are captured in the public def (user
        frame is live there) and threaded here for telemetry backfill.
        """
        # Empty string is the "not set" sentinel (ScheduledJob fields default to "").
        if not job.source_location:
            job.source_location = source_location
            job.registration_source = registration_source
        existing = self._jobs_by_name.get(job.name)
        if existing is not None:
            if if_exists == "replace":
                self.logger.debug("Replacing existing job '%s' (cancelling old, registering new)", job.name)
                self.cancel_job(existing)
            elif if_exists == "skip" and existing.matches(job):
                return existing
            elif if_exists == "skip":
                changed_fields = existing.diff_fields(job)
                raise ValueError(
                    f"A job named '{job.name}' already exists but its configuration has changed "
                    f"(changed fields: {', '.join(changed_fields)})"
                )
            else:
                raise ValueError(
                    f"A job named '{job.name}' already exists in scheduler for '{self.owner_id}'. "
                    "Job names must be unique per scheduler instance."
                )

        self._jobs_by_name[job.name] = job
        job._scheduler = self

        if job.group is not None:
            if job.group not in self._jobs_by_group:
                self._jobs_by_group[job.group] = set()
            self._jobs_by_group[job.group].add(job)

        job.set_app_error_handler_resolver(lambda: self._error_handler)
        await self.scheduler_service.add_job(job)

        return job

    def cancel_job(self, job: "ScheduledJob") -> None:
        """Cancel an individual job and persist the cancellation to the database.

        Idempotent: a second cancel on the same job is a silent no-op. Raises
        ``ValueError`` if the job belongs to a different scheduler instance.
        Spawns a durable ``mark_job_cancelled`` DB write (when ``db_id`` is set),
        dequeues the job from the service, and sets ``job._dequeued = True``.

        Must NOT call ``job.cancel()`` internally — that delegates back here and
        would cause infinite recursion.

        Args:
            job: The job to cancel.

        Raises:
            ValueError: If the job belongs to a different scheduler instance.
        """
        if job._dequeued:
            return  # idempotent — already cancelled
        if job._scheduler is not self:
            raise ValueError(
                f"cancel_job() called with a job belonging to a different scheduler "
                f"(job owner: {job._scheduler}, this scheduler: {self})"
            )
        if job.db_id is not None:
            # Spawn on scheduler_service.task_bucket (not self.task_bucket) so the
            # DB write survives Scheduler resource shutdown — the service's lifecycle
            # extends past the resource's cleanup phase.
            self.scheduler_service.task_bucket.spawn(
                self.scheduler_service.mark_job_cancelled(job.db_id),
                name="scheduler:mark_job_cancelled",
            )
        self.scheduler_service.dequeue_job(job)

    def _remove_all_jobs(self) -> asyncio.Task:
        """Remove all jobs for the owner of this scheduler."""
        self._jobs_by_name.clear()
        self._jobs_by_group.clear()
        return self.scheduler_service.remove_jobs_by_owner(self.owner_id)

    def cancel_group(self, group: str) -> None:
        """Cancel all jobs in the given group.

        Delegates to ``cancel_job`` per-member, which handles the DB write,
        dequeue, and ``_dequeued`` flag. Dict cleanup (``_jobs_by_group`` and
        ``_jobs_by_name``) is handled by the ``_on_job_removed`` callback
        fired by ``scheduler_service.dequeue_job``. No-op if the group does
        not exist.

        Args:
            group: The group name to cancel.
        """
        jobs = list(self._jobs_by_group.get(group, set()))
        for job in jobs:
            self.cancel_job(job)

    def list_jobs(self, group: str | None = None) -> list["ScheduledJob"]:
        """Return all or group-filtered jobs.

        Args:
            group: If provided, return only jobs in this group.
                If ``None`` (default), return all jobs.

        Returns:
            List of ScheduledJob instances.
        """
        if group is None:
            return list(self._jobs_by_name.values())
        return list(self._jobs_by_group.get(group, set()))

    def get_job_db_ids(self) -> list[int]:
        """Return the DB IDs of all registered jobs.

        Used by post-ready reconciliation in ``AppLifecycleService.initialize_instances()``
        to build the ``live_job_ids`` set. With synchronous registration, all jobs
        have a ``db_id`` set by the time ``on_initialize`` completes. The
        ``db_id is not None`` guard is kept as a defensive filter.

        Returns:
            List of integer DB row IDs for registered jobs.
        """
        return [job.db_id for job in self._jobs_by_name.values() if job.db_id is not None]

    def schedule(
        self,
        func: "JobCallable",
        trigger: "TriggerProtocol",
        name: str = "",
        group: str | None = None,
        jitter: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        *,
        mode: "ExecutionMode | str | None" = None,
        on_error: "SchedulerErrorHandlerType | None" = None,
        if_exists: Literal["error", "skip", "replace"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, ScheduledJob]":
        """Schedule a job using a trigger object.

        Must be awaited. Scheduling completes before the call returns.
        ``job.db_id`` is a valid integer immediately on return.

        This is the primary entry point for scheduling. All convenience methods
        (``run_in``, ``run_every``, ``run_daily``, etc.) delegate here.

        Args:
            func: The function to run.
            trigger: A trigger object implementing ``TriggerProtocol``. Determines
                both the first run time and subsequent recurrences.
            name: Optional name for the job. If empty, an auto-name is derived from
                the callable and trigger.
            group: Optional group name for bulk management (see ``cancel_group``).
            jitter: Optional seconds of random offset to apply at enqueue time.
                Jitter is applied via ``SchedulerService.apply_jitter_to_heap`` on enqueue.
                See the ``fire_at`` field on ``ScheduledJob``.
            timeout: Per-job timeout in seconds. ``None`` uses the global default.
                A positive ``float`` overrides the default.
            timeout_disabled: When ``True``, timeout enforcement is disabled for this
                job regardless of the global default.
            mode: Overlap behavior when a prior invocation is still running as the next
                occurrence becomes due. One of ``"single"`` (skip the re-fire), ``"restart"``
                (cancel the running invocation and start fresh), ``"queued"`` (serialize
                re-fires in arrival order, up to the cap), or ``"parallel"`` (run concurrently).
                A raw string is coerced to ``ExecutionMode``; an invalid string raises
                ``ValueError`` naming the valid values. Omitted (``None``) resolves
                tier-aware: ``"single"`` for app-tier jobs, ``"parallel"`` for framework-tier
                jobs. Accepted on one-shot schedules (``run_in``/``run_once``) for API
                uniformity, but has no overlap effect since one-shots never re-fire.
            on_error: Optional per-job error handler. When set, this handler is
                invoked if the job raises an exception (including ``TimeoutError``,
                but excluding ``CancelledError``). Overrides the app-level handler
                set via ``on_error()``.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job. ``job.db_id`` is a valid integer immediately on return.
        """
        if jitter is not None and jitter < 0:
            raise ValueError("jitter must be non-negative")

        if not isinstance(trigger, TriggerProtocol):
            raise TypeError(
                f"trigger must implement TriggerProtocol; got {type(trigger).__name__}. "
                "Use hassette.scheduler.triggers (After, Once, Every, Daily, Cron)"
            )

        parent = self.parent
        assert parent is not None
        app_key = parent.app_key
        instance_index = parent.index
        source_tier = parent.source_tier
        assert source_tier in ("app", "framework"), f"Invalid source_tier={source_tier!r} on {parent.class_name}"

        # Tier-aware default: an omitted mode (None) resolves to ``parallel`` for framework jobs
        # and ``single`` for app jobs. An explicit mode always wins. A raw string is coerced here
        # so an invalid value raises a clear ValueError at scheduling time (FR#8).
        if mode is None:
            resolved_mode = ExecutionMode.PARALLEL if source_tier == "framework" else ExecutionMode.SINGLE
        elif isinstance(mode, ExecutionMode):
            resolved_mode = mode
        else:
            try:
                resolved_mode = ExecutionMode(mode)
            except ValueError as exc:
                valid = ", ".join(repr(m.value) for m in ExecutionMode)
                raise ValueError(f"Invalid execution mode {mode!r}; must be one of {valid}") from exc

        run_at = trigger.first_run_time(date_utils.now())

        job = ScheduledJob(
            owner_id=self.owner_id,
            next_run=run_at,
            job=func,
            trigger=trigger,
            name=name,
            group=group,
            jitter=jitter,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            args=tuple(args) if args else (),
            kwargs=dict(kwargs) if kwargs else {},
            error_handler=on_error,
            app_key=app_key,
            instance_index=instance_index,
            source_tier=source_tier,
            mode=resolved_mode,
        )
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at add_job (the true primary). See design/071.
        # source_location/registration_source are NOT passed here; add_job backfills them.
        return self.add_job(job, if_exists=if_exists)

    def run_in(
        self,
        func: "JobCallable",
        delay: float,
        name: str = "",
        group: str | None = None,
        jitter: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        *,
        mode: "ExecutionMode | str | None" = None,
        on_error: "SchedulerErrorHandlerType | None" = None,
        if_exists: Literal["error", "skip", "replace"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, ScheduledJob]":
        """Schedule a job to run after a fixed delay (one-shot).

        Must be awaited. Scheduling completes before the call returns.
        ``job.db_id`` is a valid integer immediately on return.

        Args:
            func: The function to run.
            delay: The delay in seconds before running the job.
            name: Optional name for the job.
            group: Optional group name.
            jitter: Optional seconds of random offset to apply at enqueue time.
                See ``schedule()`` for details.
            timeout: Per-job timeout in seconds. See ``schedule()`` for details.
            timeout_disabled: Disable timeout enforcement. See ``schedule()`` for details.
            mode: Overlap mode. Accepted for API uniformity; has no overlap effect for
                one-shot jobs since they never re-fire. See ``schedule()`` for the four
                values, tier-aware default, and string coercion rules.
            on_error: Optional per-job error handler. See ``schedule()`` for details.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        trigger = After(seconds=float(delay))
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at add_job (the true primary). See design/071.
        return self.schedule(
            func,
            trigger,
            name=name,
            group=group,
            jitter=jitter,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            mode=mode,
            on_error=on_error,
            if_exists=if_exists,
            args=args,
            kwargs=kwargs,
        )

    def run_once(
        self,
        func: "JobCallable",
        at: str | ZonedDateTime,
        name: str = "",
        group: str | None = None,
        jitter: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        if_past: Literal["tomorrow", "error"] = "tomorrow",
        *,
        mode: "ExecutionMode | str | None" = None,
        on_error: "SchedulerErrorHandlerType | None" = None,
        if_exists: Literal["error", "skip", "replace"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, ScheduledJob]":
        """Schedule a job to run once at a specific wall-clock time (one-shot).

        Must be awaited. Scheduling completes before the call returns.
        ``job.db_id`` is a valid integer immediately on return.

        Args:
            func: The function to run.
            at: Target time. A ``"HH:MM"`` string (today in system timezone, or
                tomorrow if already past) or a ``ZonedDateTime``.
            name: Optional name for the job.
            group: Optional group name.
            jitter: Optional seconds of random offset to apply at enqueue time.
                See ``schedule()`` for details.
            timeout: Per-job timeout in seconds. See ``schedule()`` for details.
            timeout_disabled: Disable timeout enforcement. See ``schedule()`` for details.
            if_past: Behaviour when the target time is in the past at construction
                time. ``"tomorrow"`` (default) defers by one day. ``"error"`` raises
                ``ValueError``. For ``ZonedDateTime`` inputs, ``if_past`` has no
                effect — the job always fires immediately if the instant is in the past.
            mode: Overlap mode. Accepted for API uniformity; has no overlap effect for
                one-shot jobs since they never re-fire. See ``schedule()`` for the four
                values, tier-aware default, and string coercion rules.
            on_error: Optional per-job error handler. See ``schedule()`` for details.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        trigger = Once(at=at, if_past=if_past)
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at add_job (the true primary). See design/071.
        return self.schedule(
            func,
            trigger,
            name=name,
            group=group,
            jitter=jitter,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            mode=mode,
            on_error=on_error,
            if_exists=if_exists,
            args=args,
            kwargs=kwargs,
        )

    def run_every(
        self,
        func: "JobCallable",
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        name: str = "",
        group: str | None = None,
        jitter: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        *,
        mode: "ExecutionMode | str | None" = None,
        on_error: "SchedulerErrorHandlerType | None" = None,
        if_exists: Literal["error", "skip", "replace"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, ScheduledJob]":
        """Schedule a job to run at a fixed interval.

        Must be awaited. Scheduling completes before the call returns.
        ``job.db_id`` is a valid integer immediately on return.

        Args:
            func: The function to run.
            hours: Interval hours component.
            minutes: Interval minutes component.
            seconds: Interval seconds component.
            name: Optional name for the job.
            group: Optional group name.
            jitter: Optional seconds of random offset to apply at enqueue time.
                See ``schedule()`` for details.
            timeout: Per-job timeout in seconds. See ``schedule()`` for details.
            timeout_disabled: Disable timeout enforcement. See ``schedule()`` for details.
            mode: Overlap behavior when a prior invocation is still running as the next
                tick becomes due. See ``schedule()`` for the four values, tier-aware
                default, and string coercion rules.
            on_error: Optional per-job error handler. See ``schedule()`` for details.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        trigger = Every(hours=hours, minutes=minutes, seconds=seconds)
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at add_job (the true primary). See design/071.
        return self.schedule(
            func,
            trigger,
            name=name,
            group=group,
            jitter=jitter,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            mode=mode,
            on_error=on_error,
            if_exists=if_exists,
            args=args,
            kwargs=kwargs,
        )

    def run_minutely(
        self,
        func: "JobCallable",
        minutes: int = 1,
        name: str = "",
        group: str | None = None,
        jitter: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        *,
        mode: "ExecutionMode | str | None" = None,
        on_error: "SchedulerErrorHandlerType | None" = None,
        if_exists: Literal["error", "skip", "replace"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, ScheduledJob]":
        """Schedule a job to run every N minutes.

        Must be awaited. Scheduling completes before the call returns.
        ``job.db_id`` is a valid integer immediately on return.

        Args:
            func: The function to run.
            minutes: The minute interval (must be >= 1).
            name: Optional name for the job.
            group: Optional group name.
            jitter: Optional seconds of random offset to apply at enqueue time.
                See ``schedule()`` for details.
            timeout: Per-job timeout in seconds. See ``schedule()`` for details.
            timeout_disabled: Disable timeout enforcement. See ``schedule()`` for details.
            mode: Overlap behavior when a prior invocation is still running as the next
                tick becomes due. See ``schedule()`` for the four values, tier-aware
                default, and string coercion rules.
            on_error: Optional per-job error handler. See ``schedule()`` for details.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        if minutes < 1:
            raise ValueError("Minute interval must be at least 1")
        trigger = Every(minutes=minutes)
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at add_job (the true primary). See design/071.
        return self.schedule(
            func,
            trigger,
            name=name,
            group=group,
            jitter=jitter,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            mode=mode,
            on_error=on_error,
            if_exists=if_exists,
            args=args,
            kwargs=kwargs,
        )

    def run_hourly(
        self,
        func: "JobCallable",
        hours: int = 1,
        name: str = "",
        group: str | None = None,
        jitter: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        *,
        mode: "ExecutionMode | str | None" = None,
        on_error: "SchedulerErrorHandlerType | None" = None,
        if_exists: Literal["error", "skip", "replace"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, ScheduledJob]":
        """Schedule a job to run every N hours.

        Must be awaited. Scheduling completes before the call returns.
        ``job.db_id`` is a valid integer immediately on return.

        Args:
            func: The function to run.
            hours: The hour interval (must be >= 1).
            name: Optional name for the job.
            group: Optional group name.
            jitter: Optional seconds of random offset to apply at enqueue time.
                See ``schedule()`` for details.
            timeout: Per-job timeout in seconds. See ``schedule()`` for details.
            timeout_disabled: Disable timeout enforcement. See ``schedule()`` for details.
            mode: Overlap behavior when a prior invocation is still running as the next
                tick becomes due. See ``schedule()`` for the four values, tier-aware
                default, and string coercion rules.
            on_error: Optional per-job error handler. See ``schedule()`` for details.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        if hours < 1:
            raise ValueError("Hour interval must be at least 1")
        trigger = Every(hours=hours)
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at add_job (the true primary). See design/071.
        return self.schedule(
            func,
            trigger,
            name=name,
            group=group,
            jitter=jitter,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            mode=mode,
            on_error=on_error,
            if_exists=if_exists,
            args=args,
            kwargs=kwargs,
        )

    def run_daily(
        self,
        func: "JobCallable",
        at: str = "00:00",
        name: str = "",
        group: str | None = None,
        jitter: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        *,
        mode: "ExecutionMode | str | None" = None,
        on_error: "SchedulerErrorHandlerType | None" = None,
        if_exists: Literal["error", "skip", "replace"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, ScheduledJob]":
        """Schedule a job to run once per day at a fixed wall-clock time.

        Must be awaited. Scheduling completes before the call returns.
        ``job.db_id`` is a valid integer immediately on return.

        Uses a cron-based trigger internally to ensure DST-correct, wall-clock-aligned
        scheduling. This avoids the 24-hour drift bug of interval-based daily scheduling.

        Args:
            func: The function to run.
            at: Target wall-clock time in ``"HH:MM"`` format (default ``"00:00"``).
            name: Optional name for the job.
            group: Optional group name.
            jitter: Optional seconds of random offset to apply at enqueue time.
                See ``schedule()`` for details.
            timeout: Per-job timeout in seconds. See ``schedule()`` for details.
            timeout_disabled: Disable timeout enforcement. See ``schedule()`` for details.
            mode: Overlap behavior when a prior invocation is still running as the next
                tick becomes due. See ``schedule()`` for the four values, tier-aware
                default, and string coercion rules.
            on_error: Optional per-job error handler. See ``schedule()`` for details.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        trigger = Daily(at=at)
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at add_job (the true primary). See design/071.
        return self.schedule(
            func,
            trigger,
            name=name,
            group=group,
            jitter=jitter,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            mode=mode,
            on_error=on_error,
            if_exists=if_exists,
            args=args,
            kwargs=kwargs,
        )

    def run_cron(
        self,
        func: "JobCallable",
        expression: str,
        name: str = "",
        group: str | None = None,
        jitter: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        *,
        mode: "ExecutionMode | str | None" = None,
        on_error: "SchedulerErrorHandlerType | None" = None,
        if_exists: Literal["error", "skip", "replace"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, ScheduledJob]":
        """Schedule a job using a cron expression.

        Must be awaited. Scheduling completes before the call returns.
        ``job.db_id`` is a valid integer immediately on return.

        Accepts both 5-field (standard Unix cron: ``minute hour dom month dow``)
        and 6-field expressions (seconds appended as a 6th field per croniter
        convention: ``minute hour dom month dow second``).

        Args:
            func: The function to run.
            expression: A valid 5- or 6-field cron expression.
            name: Optional name for the job.
            group: Optional group name.
            jitter: Optional seconds of random offset to apply at enqueue time.
                See ``schedule()`` for details.
            timeout: Per-job timeout in seconds. See ``schedule()`` for details.
            timeout_disabled: Disable timeout enforcement. See ``schedule()`` for details.
            mode: Overlap behavior when a prior invocation is still running as the next
                tick becomes due. See ``schedule()`` for the four values, tier-aware
                default, and string coercion rules.
            on_error: Optional per-job error handler. See ``schedule()`` for details.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.

        Raises:
            ValueError: If the cron expression is syntactically invalid.
        """
        trigger = Cron(expression)
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at add_job (the true primary). See design/071.
        return self.schedule(
            func,
            trigger,
            name=name,
            group=group,
            jitter=jitter,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            mode=mode,
            on_error=on_error,
            if_exists=if_exists,
            args=args,
            kwargs=kwargs,
        )
