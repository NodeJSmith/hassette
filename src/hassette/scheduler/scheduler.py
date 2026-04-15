"""
Scheduler for running tasks at specific times or intervals with flexible triggers.

The Scheduler provides intuitive methods for scheduling one-time and recurring tasks using
trigger objects, simple time delays, cron expressions, or daily wall-clock times. Jobs are
automatically cleaned up when the app shuts down, and support both async and sync callables.

Examples:
    One-time delayed execution::

        # Run in 30 seconds
        self.scheduler.run_in(self.cleanup_task, 30)

        # Run once at 7:00 AM today (or tomorrow if 07:00 has already passed)
        self.scheduler.run_once(self.morning_routine, at="07:00")

    Recurring execution::

        # Every 5 minutes
        self.scheduler.run_every(self.check_sensors, minutes=5)

        # Every hour
        self.scheduler.run_hourly(self.log_status)

        # Every day at 6:30 AM (wall-clock anchored, DST-safe)
        self.scheduler.run_daily(self.morning_routine, at="06:30")

        # Every 5 minutes
        self.scheduler.run_minutely(self.quick_check, minutes=5)

    Cron-style scheduling::

        # Weekdays at 9 AM
        self.scheduler.run_cron(self.workday_routine, "0 9 * * 1-5")

    Job groups::

        # Schedule multiple jobs in a named group for bulk cancellation
        self.scheduler.run_daily(self.open_blinds, at="08:00", group="morning")
        self.scheduler.run_daily(self.play_music, at="08:05", group="morning")

        # Cancel all jobs in the group
        self.scheduler.cancel_group("morning")

    Using the primary entry point directly::

        from hassette.scheduler import Every, Daily, Cron

        job = self.scheduler.schedule(self.my_func, Every(hours=1))
        job = self.scheduler.schedule(self.my_func, Daily(at="07:00"), group="morning")
        job = self.scheduler.schedule(self.my_func, Cron("0 9 * * 1-5"))

    Job management::

        # Named job for easier management
        job = self.scheduler.run_daily(self.backup_data, at="02:00", name="daily_backup")

        # Cancel a specific job
        job.cancel()
"""

import asyncio
import typing
from collections.abc import Mapping
from contextlib import suppress
from typing import Any, Literal

from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.core.scheduler_service import SchedulerService
from hassette.resources.base import Resource
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.source_capture import capture_registration_source

from .classes import ScheduledJob
from .triggers import After, Cron, Daily, Every, Once

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.types import JobCallable, TriggerProtocol


class Scheduler(Resource):
    """Scheduler resource for managing scheduled jobs."""

    scheduler_service: SchedulerService
    """The scheduler service instance."""

    _jobs_by_name: dict[str, "ScheduledJob"]
    """Tracks jobs by name for uniqueness validation within this scheduler instance."""

    _jobs_by_group: dict[str, list["ScheduledJob"]]
    """Tracks jobs by group for bulk cancellation."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.scheduler_service = self.hassette._scheduler_service
        assert self.scheduler_service is not None, "Scheduler service not initialized"
        self._jobs_by_name = {}
        self._jobs_by_group: dict[str, list[ScheduledJob]] = {}

        # Register removal callback so exhausted one-shot jobs are removed from _jobs_by_group
        # automatically when SchedulerService removes them after firing.
        # WP04 adds register_removal_callback() to SchedulerService; guard on isinstance (not
        # just hasattr) so that AsyncMock stubs in tests don't accidentally call the method and
        # produce unawaited-coroutine warnings.
        _register = getattr(self.scheduler_service, "register_removal_callback", None)
        if isinstance(self.scheduler_service, SchedulerService) and callable(_register):
            _register(self.owner_id, self._on_job_removed)

    def _on_job_removed(self, job: "ScheduledJob") -> None:
        """Callback invoked by SchedulerService when a job is auto-exhausted.

        Keeps _jobs_by_group and _jobs_by_name in sync when SchedulerService removes a
        one-shot job after it fires (without the caller explicitly calling remove_job).
        """
        self._jobs_by_name.pop(job.name, None)
        if job.group is not None:
            group_list = self._jobs_by_group.get(job.group)
            if group_list is not None:
                with suppress(ValueError):
                    group_list.remove(job)
                if not group_list:
                    del self._jobs_by_group[job.group]

    async def on_initialize(self) -> None:
        self.mark_ready(reason="Scheduler initialized")

    async def on_shutdown(self) -> None:
        await self.remove_all_jobs()

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.scheduler_service_log_level

    def add_job(self, job: "ScheduledJob", *, if_exists: Literal["error", "skip"] = "error") -> "ScheduledJob":
        """Add a job to the scheduler.

        Args:
            job: The job to add.
            if_exists: Behavior when a job with the same name already exists.
                ``"error"`` (default) raises ``ValueError``.
                ``"skip"`` returns the existing job if it matches; raises
                ``ValueError`` if the name matches but the configuration differs.

        Returns:
            The added job, or the existing job when ``if_exists="skip"`` and a
            matching job is already registered.

        Raises:
            TypeError: If job is not a ScheduledJob.
            ValueError: If a job with the same name already exists and either
                ``if_exists="error"`` or the existing job's configuration differs.
        """

        if not isinstance(job, ScheduledJob):
            raise TypeError(f"Expected ScheduledJob, got {type(job).__name__}")

        existing = self._jobs_by_name.get(job.name)
        if existing is not None:
            if if_exists == "skip" and existing.matches(job):
                return existing
            raise ValueError(
                f"A job named '{job.name}' already exists in scheduler for '{self.owner_id}'. "
                "Job names must be unique per scheduler instance."
            )

        self._jobs_by_name[job.name] = job

        if job.group is not None:
            if job.group not in self._jobs_by_group:
                self._jobs_by_group[job.group] = []
            self._jobs_by_group[job.group].append(job)

        self.scheduler_service.add_job(job)

        return job

    def remove_job(self, job: "ScheduledJob") -> asyncio.Task:
        """Remove a job from the scheduler.

        Args:
            job: The job to remove.
        """
        self._jobs_by_name.pop(job.name, None)

        if job.group is not None:
            group_list = self._jobs_by_group.get(job.group)
            if group_list is not None:
                with suppress(ValueError):
                    group_list.remove(job)
                if not group_list:
                    del self._jobs_by_group[job.group]

        return self.scheduler_service.remove_job(job)

    def remove_all_jobs(self) -> asyncio.Task:
        """Remove all jobs for the owner of this scheduler."""
        self._jobs_by_name.clear()
        self._jobs_by_group.clear()
        return self.scheduler_service.remove_jobs_by_owner(self.owner_id)

    def cancel_group(self, group: str) -> None:
        """Cancel all jobs in the given group.

        Marks each job as cancelled, removes it from the scheduler service queue,
        and clears the group entry from ``_jobs_by_group``. No-op if the group
        does not exist.

        Args:
            group: The group name to cancel.
        """
        jobs = list(self._jobs_by_group.get(group, []))
        for job in jobs:
            job.cancel()
            self.scheduler_service.remove_job(job)
        if group in self._jobs_by_group:
            del self._jobs_by_group[group]
        # Also remove from _jobs_by_name
        for job in jobs:
            self._jobs_by_name.pop(job.name, None)

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
        return list(self._jobs_by_group.get(group, []))

    def get_job_db_ids(self) -> list[int]:
        """Return the DB IDs of all registered jobs that have been persisted.

        Used by post-ready reconciliation in ``AppLifecycleService.initialize_instances()``
        to build the ``live_job_ids`` set. Jobs whose ``db_id`` is still ``None``
        (registration pending) are excluded.

        Returns:
            List of integer DB row IDs for registered jobs with a resolved ``db_id``.
        """
        return [job.db_id for job in self._jobs_by_name.values() if job.db_id is not None]

    def schedule(
        self,
        func: "JobCallable",
        trigger: "TriggerProtocol",
        name: str = "",
        group: str | None = None,
        jitter: float | None = None,
        *,
        if_exists: Literal["error", "skip"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job using a trigger object.

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
                Implementation deferred to WP06.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """

        app_key = getattr(self.parent, "app_key", "") if self.parent else ""
        instance_index = getattr(self.parent, "index", 0) if self.parent else 0

        # Capture source while user code is still on the stack (before async spawn boundary)
        source_location, registration_source = capture_registration_source()

        run_at = trigger.first_run_time(date_utils.now())

        job = ScheduledJob(
            owner_id=self.owner_id,
            next_run=run_at,
            job=func,
            trigger=trigger,
            name=name,
            group=group,
            jitter=jitter,
            args=tuple(args) if args else (),
            kwargs=dict(kwargs) if kwargs else {},
            app_key=app_key,
            instance_index=instance_index,
            source_location=source_location,
            registration_source=registration_source or "",
        )
        return self.add_job(job, if_exists=if_exists)

    def run_in(
        self,
        func: "JobCallable",
        delay: float,
        name: str = "",
        group: str | None = None,
        *,
        if_exists: Literal["error", "skip"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run after a fixed delay (one-shot).

        Args:
            func: The function to run.
            delay: The delay in seconds before running the job.
            name: Optional name for the job.
            group: Optional group name.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        trigger = After(seconds=float(delay))
        return self.schedule(func, trigger, name=name, group=group, if_exists=if_exists, args=args, kwargs=kwargs)

    def run_once(
        self,
        func: "JobCallable",
        at: str | ZonedDateTime,
        name: str = "",
        group: str | None = None,
        *,
        if_exists: Literal["error", "skip"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run once at a specific wall-clock time (one-shot).

        Args:
            func: The function to run.
            at: Target time. A ``"HH:MM"`` string (today in system timezone, or
                tomorrow if already past) or a ``ZonedDateTime``.
            name: Optional name for the job.
            group: Optional group name.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        trigger = Once(at=at)
        return self.schedule(func, trigger, name=name, group=group, if_exists=if_exists, args=args, kwargs=kwargs)

    def run_every(
        self,
        func: "JobCallable",
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        name: str = "",
        group: str | None = None,
        *,
        if_exists: Literal["error", "skip"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run at a fixed interval.

        Args:
            func: The function to run.
            hours: Interval hours component.
            minutes: Interval minutes component.
            seconds: Interval seconds component.
            name: Optional name for the job.
            group: Optional group name.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        trigger = Every(hours=hours, minutes=minutes, seconds=seconds)
        return self.schedule(func, trigger, name=name, group=group, if_exists=if_exists, args=args, kwargs=kwargs)

    def run_minutely(
        self,
        func: "JobCallable",
        minutes: int = 1,
        name: str = "",
        group: str | None = None,
        *,
        if_exists: Literal["error", "skip"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N minutes.

        Args:
            func: The function to run.
            minutes: The minute interval (must be >= 1).
            name: Optional name for the job.
            group: Optional group name.
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
        return self.schedule(func, trigger, name=name, group=group, if_exists=if_exists, args=args, kwargs=kwargs)

    def run_hourly(
        self,
        func: "JobCallable",
        hours: int = 1,
        name: str = "",
        group: str | None = None,
        *,
        if_exists: Literal["error", "skip"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N hours.

        Args:
            func: The function to run.
            hours: The hour interval (must be >= 1).
            name: Optional name for the job.
            group: Optional group name.
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
        return self.schedule(func, trigger, name=name, group=group, if_exists=if_exists, args=args, kwargs=kwargs)

    def run_daily(
        self,
        func: "JobCallable",
        at: str = "00:00",
        name: str = "",
        group: str | None = None,
        *,
        if_exists: Literal["error", "skip"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run once per day at a fixed wall-clock time.

        Uses a cron-based trigger internally to ensure DST-correct, wall-clock-aligned
        scheduling. This avoids the 24-hour drift bug of interval-based daily scheduling.

        Args:
            func: The function to run.
            at: Target wall-clock time in ``"HH:MM"`` format (default ``"00:00"``).
            name: Optional name for the job.
            group: Optional group name.
            if_exists: Behavior when a job with the same name already exists.
                See :meth:`add_job` for details.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        trigger = Daily(at=at)
        return self.schedule(func, trigger, name=name, group=group, if_exists=if_exists, args=args, kwargs=kwargs)

    def run_cron(
        self,
        func: "JobCallable",
        expression: str,
        name: str = "",
        group: str | None = None,
        *,
        if_exists: Literal["error", "skip"] = "error",
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job using a cron expression.

        Accepts both 5-field (standard Unix cron: ``minute hour dom month dow``)
        and 6-field expressions (seconds appended as a 6th field per croniter
        convention: ``minute hour dom month dow second``).

        Args:
            func: The function to run.
            expression: A valid 5- or 6-field cron expression.
            name: Optional name for the job.
            group: Optional group name.
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
        return self.schedule(func, trigger, name=name, group=group, if_exists=if_exists, args=args, kwargs=kwargs)
