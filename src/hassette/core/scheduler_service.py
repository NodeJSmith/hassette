import asyncio
import typing
from collections.abc import Callable
from typing import ClassVar

from hassette_wire import LogLevel, ScheduleStatus
from whenever import TimeDelta, ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.core.database_service import DatabaseService
from hassette.core.registration import ScheduledJobRegistration
from hassette.core.scheduler_dispatch import SchedulerDispatchMixin
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.exceptions import JobRemovedError, TaskBucketSealedError
from hassette.execution_mode import release_and_drain
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_not_ready, mark_ready
from hassette.resources.restart import CORE_PERMANENT_RESTART
from hassette.resources.service import Service
from hassette.scheduler.job_queue import _ScheduledJobQueue
from hassette.utils.func_utils import callable_stable_name, describe_predicate
from hassette.utils.serialization import safe_json_serialize

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.command_executor import CommandExecutor
    from hassette.scheduler.classes import Job


class SchedulerService(SchedulerDispatchMixin, Service):
    """Service that manages scheduled jobs."""

    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService, SyncExecutorService]
    restart_spec = CORE_PERMANENT_RESTART

    _job_queue: "_ScheduledJobQueue"
    """Queue of scheduled jobs."""

    _wakeup_event: asyncio.Event
    """Event to wake the scheduler when a new job is added or jobs are removed."""

    _exit_event: asyncio.Event
    """Event to signal the scheduler to exit."""

    _executor: "CommandExecutor"
    """Command executor for running jobs and persisting registration/execution records."""

    _removal_callbacks: dict[str, Callable[["Job"], None]]
    """Per-owner callbacks invoked whenever a job is removed via dequeue_job() or _remove_jobs()."""

    _jobs_by_id: dict[int, "Job"]
    """Service-level live registry: the authority for live runtime existence and O(1) API
    lookup, independent of heap membership. Populated only after persistence assigns
    ``db_id`` (see ``add_job()``); mutated only through identity-checked helpers
    (``deregister_job()``) since a crash-restart cycle can leave an orphaned ``Job`` sharing
    a ``db_id`` with a freshly re-registered live job (the upsert reuses the natural-key row).
    """

    def __init__(self, hassette: "Hassette", *, executor: "CommandExecutor", parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._executor = executor
        self._job_queue = self.add_child(_ScheduledJobQueue)
        self._wakeup_event = asyncio.Event()
        self._exit_event = asyncio.Event()
        self._removal_callbacks = {}
        self._jobs_by_id = {}

    @property
    def min_delay(self) -> float:
        return self.hassette.config.scheduler.min_delay_seconds

    @property
    def max_delay(self) -> float:
        return self.hassette.config.scheduler.max_delay_seconds

    @property
    def default_delay(self) -> float:
        return self.hassette.config.scheduler.default_delay_seconds

    @property
    def config_log_level(self) -> LogLevel:
        return self.hassette.config.logging.scheduler_service

    async def before_initialize(self) -> None:
        await self.hassette.ready_event.wait()

    async def serve(self) -> None:
        """Run the scheduler forever, processing jobs as they become due."""
        mark_ready(self, reason="Scheduler started")

        while True:
            if self.shutdown_event.is_set():
                mark_not_ready(self, reason="Hassette is shutting down")
                self.logger.debug("Scheduler exiting")
                return

            due_jobs, next_run_time = await self._job_queue.pop_due_and_peek_next(date_utils.now())

            if due_jobs:
                for job in due_jobs:
                    self.task_bucket.spawn(self.dispatch_and_log(job), name="scheduler:dispatch_scheduled_job")

            await self.sleep(next_run_time)

    def register_removal_callback(self, owner_id: str, callback: Callable[["Job"], None]) -> None:
        """Register a callback to be called whenever a job belonging to owner_id is removed.

        If a callback is already registered for owner_id, the new callback replaces it.
        This handles legitimate re-registration during hot-reload cycles where the old
        Scheduler instance is orphaned without a formal shutdown.

        Args:
            owner_id: The owner whose job removals should trigger the callback.
            callback: Called with the removed Job as its single argument.
        """
        self._removal_callbacks[owner_id] = callback

    def deregister_removal_callback(self, owner_id: str) -> None:
        """Remove the removal callback for owner_id, if any.

        No-op when owner_id has no registered callback. Called by
        ``Scheduler.on_shutdown`` so the slot is freed before the Scheduler
        is re-initialized (e.g. during a hot-reload cycle).

        Args:
            owner_id: The owner whose callback should be removed.
        """
        self._removal_callbacks.pop(owner_id, None)

    def fire_removal_callbacks(self, jobs: "list[Job]") -> None:
        """Invoke per-owner removal callbacks for each job in jobs."""
        for job in jobs:
            callback = self._removal_callbacks.get(job.owner_id)
            if callback is not None:
                callback(job)

    async def sleep(self, next_run_time: ZonedDateTime | None = None) -> None:
        """Sleep until the next job is due or a kick is received.

        This method will wait for the next job to be due or until a kick is received.
        If a kick is received, it will wake up immediately.

        Args:
            next_run_time: Pre-fetched next run time to avoid an extra lock acquisition.
                If None, uses the default delay.
        """
        try:
            timeout = self.calculate_sleep_time(next_run_time).total("seconds")
            await asyncio.wait_for(self._wakeup_event.wait(), timeout=timeout)
            self.logger.debug("Scheduler woke up due to kick")
        except asyncio.CancelledError:
            self.logger.debug("Scheduler sleep cancelled")
            raise
        except TimeoutError:
            self.logger.debug("Scheduler woke up due to timeout")
        finally:
            self._wakeup_event.clear()

    def calculate_sleep_time(self, next_run_time: ZonedDateTime | None) -> TimeDelta:
        """Calculate the time to sleep until the next job is due.

        Args:
            next_run_time: The next scheduled run time, or None if no jobs are queued.
        """
        if next_run_time is not None:
            self.logger.debug("Next job scheduled at %s", next_run_time)
            delay = max((next_run_time - date_utils.now()).total("seconds"), self.min_delay)
        else:
            delay = self.default_delay

        delay = min(delay, self.max_delay)
        self.logger.debug("Scheduler sleeping for %s seconds", delay)

        return TimeDelta(seconds=delay)

    async def add_job(self, job: "Job") -> None:
        """Register the job: persist it, add it to the live registry, then enqueue if due.

        Three steps, in order:

        1. Persist the registration and assign ``db_id`` — awaited inline, so ``job.db_id``
           is set before this method returns. This eliminates the window where a job fires
           with ``db_id=None``.
        2. Add the job to ``_jobs_by_id`` — the service-level live registry, independent of
           heap membership.
        3. Enqueue only when ``job.schedule_status is ScheduleStatus.SCHEDULED``. A waiting,
           completed, or manual-only job is registered and addressable but never touches the
           heap — ``_ScheduledJobQueue.add()`` rejects any other status.

        Trigger type dispatch uses the TriggerProtocol methods exclusively.
        Non-protocol triggers are rejected synchronously by ``Scheduler.schedule()``
        before reaching this path.
        """
        source_location = job.source_location
        registration_source: str | None = job.registration_source or None
        trigger = job.trigger
        if trigger is not None:
            trigger_type: str = trigger.trigger_db_type()
            trigger_label: str = trigger.trigger_label()
            trigger_detail: str | None = trigger.trigger_detail()
        else:
            # A manual-only job registered via Scheduler.register() — no trigger at all.
            # "manual" is reserved for this path; custom triggers use trigger_db_type()'s
            # own "custom" value instead.
            trigger_type = "manual"
            trigger_label = "Manual only"
            trigger_detail = None

        predicate_description: str | None = None
        human_description: str | None = None
        if job.predicate is not None:
            predicate_description = describe_predicate(job.predicate)
            if hasattr(job.predicate, "summarize"):
                human_description = job.predicate.summarize()  # pyright: ignore[reportFunctionMemberAccess]
            else:
                human_description = callable_stable_name(job.predicate)

        reg = ScheduledJobRegistration(
            app_key=job.app_key,
            instance_index=job.instance_index,
            job_name=job.name,
            handler_method=getattr(job.job, "__qualname__", str(job.job)),
            trigger_type=trigger_type,
            trigger_label=trigger_label,
            trigger_detail=trigger_detail,
            args_json=safe_json_serialize(list(job.args)),
            kwargs_json=safe_json_serialize(job.kwargs),
            source_location=source_location,
            registration_source=registration_source,
            source_tier=job.source_tier,
            group=job.group,
            mode=job.mode,
            predicate_description=predicate_description,
            human_description=human_description,
            schedule_status=job.schedule_status,
            schedule_status_reason=job.schedule_status_reason,
        )
        job.mark_registered(await self._executor.register_job(reg))
        # db_id can stay None here — a degraded registration write (or a test double)
        # returns no row id. Such a job is never registry-addressable, but scheduling
        # still proceeds unchanged: enqueue is driven by schedule_status alone.
        if job.db_id is not None:
            self._jobs_by_id[job.db_id] = job
        if job.schedule_status is ScheduleStatus.SCHEDULED:
            await self.enqueue_job(job)

    async def get_all_jobs(self) -> list["Job"]:
        """Return all live registered jobs across all apps.

        Sourced from ``_jobs_by_id`` — the service-level live registry — not the due-time
        heap, so waiting, completed, and manual-only jobs (which never touch the heap) are
        included alongside scheduled ones. This is a synchronous dict-values snapshot; unlike
        the heap's ``_ScheduledJobQueue.get_all()``, no lock is needed since ``_jobs_by_id``
        mutations happen only on the event loop thread.
        """
        return list(self._jobs_by_id.values())

    async def trigger_job(self, job_id: int) -> "Job":
        """Look up a job in the live registry by its database id.

        Used by the manual-submission route handler (``POST /api/scheduler/jobs/{job_id}/trigger``)
        to find the job to submit. Only looks up and returns the job — the caller is
        responsible for calling ``submit_job()``.

        Args:
            job_id: The job's ``scheduled_jobs.id`` database row id (``Job.db_id``).

        Returns:
            The matching Job from the live registry, regardless of its ``schedule_status``.

        Raises:
            ValueError: If no job with the given job_id is currently registered — the
                registration was never made, was removed, or the owning app is not running.
        """
        live_jobs = await self.get_all_jobs()
        live_by_job_id = {job.db_id: job for job in live_jobs if job.db_id is not None}
        job = live_by_job_id.get(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} is not currently triggerable")
        return job

    def _remove_from_live_state(self, job: "Job") -> bool:
        """Synchronous core of the unified removal operation: registry, heap, callbacks.

        Removes ``job`` from the live registry (``_jobs_by_id``, identity-checked via
        ``deregister_job``) first, so no concurrent ``submit_job()`` call can be accepted
        once this returns. Then marks the private ``_dequeued`` flag, removes any heap
        occurrence via ``_ScheduledJobQueue.remove_item_sync`` (no lock), kicks the
        scheduler when the job was actually heap-resident, and fires per-owner removal
        callbacks unconditionally — even when the job was never on the heap (waiting,
        completed, manual, or already popped by the serve loop) — to prevent dict leaks
        in ``Scheduler._jobs_by_name``/``_jobs_by_group``.

        Every step here runs to completion with no ``await`` point, which is required so
        callers with no way to await a removal (``dequeue_job()``'s synchronous entry
        point, used by ``Job.remove()``/``Scheduler.remove_job()``) still get the
        no-new-submission and index-cleanup guarantees synchronously, before this method
        returns.

        Args:
            job: The job to remove from live state.

        Returns:
            True if the job was found and removed from the heap, False otherwise.
        """
        self.deregister_job(job)
        removed_from_heap = self._job_queue.remove_item_sync(job)
        if removed_from_heap:
            self.logger.debug("Dequeued job: %s", job)
            self.kick()
        else:
            self.logger.debug("Job not in heap (already popped by serve loop, or never enqueued): %s", job)
        # Set _dequeued unconditionally — even when the job was already popped
        # from the heap by the serve loop. This prevents the dispatch race
        # (guard in dispatch_and_log) and makes removal idempotent.
        job._dequeued = True
        self.fire_removal_callbacks([job])
        return removed_from_heap

    async def _finish_removal(self, job: "Job", *, detach_self: bool = False) -> None:
        """Async tail of the unified removal operation: guard release, drain, persistence.

        Releases ``job``'s ``ExecutionModeGuard`` — cancels an active ``single``/
        ``restart`` invocation, drains a queued ``queued``-mode factory (so a dispatch task
        parked on ``await done`` unwinds instead of hanging — see
        ``run_through_guard``/``drain_pending_done``); a no-op for ``parallel``, whose guard
        tracks no invocation. With ``detach_self`` (``if_exists="replace"``), an invocation removing
        its own job from its callback is left to finish rather than cancelled — see
        ``ExecutionModeGuard.release``. Then persists ``removed_at`` when the job was ever assigned a
        ``db_id`` — no-op for a job whose registration never reached persistence.

        Args:
            job: The job whose guard/pending futures/persistence should be finalized.
            detach_self: Detach rather than cancel the job's invocation when the removal runs
                from that invocation's own callback.
        """
        await release_and_drain(job.guard, job.pending_done, detach_self=detach_self)
        if job.db_id is not None:
            await self.mark_job_removed(job.db_id)

    def dequeue_job(self, job: "Job") -> bool:
        """Synchronous entry point for the unified removal operation.

        Used by ``Scheduler.remove_job()``/``remove_group()`` — the public, non-awaited
        removal API — which has no way to await the guard-release/persistence tail. Runs
        ``_remove_from_live_state()`` inline (registry, heap, ``_dequeued`` flag,
        callbacks) and spawns ``_finish_removal()`` as a fire-and-forget task on this
        service's own ``task_bucket`` so the guard release and ``removed_at`` write survive
        the caller's own shutdown/cancellation window.

        When that bucket is already sealed (reachable only after a force-terminal teardown,
        which seals without running hooks), the tail is skipped with a debug log rather than
        raising: the guard is left unreleased and ``removed_at`` is never persisted for this
        job. Live state removal still happens either way. Only that sealed rejection is
        absorbed — any other ``spawn()`` failure still propagates.

        Args:
            job: The job to remove.

        Returns:
            True if the job was found and removed from the heap, False otherwise.
        """
        removed_from_heap = self._remove_from_live_state(job)
        try:
            self.task_bucket.spawn(self._finish_removal(job), name="scheduler:guard_release")
        except TaskBucketSealedError:
            # Accepted gap (force-terminal only): both the guard release and the removed_at
            # persistence write are skipped, not just cleanup — mark_job_removed() never runs for
            # this job. Narrower than the listener-side gap (real data, not just in-memory state),
            # but the same trigger applies, and a force-terminated service's process exits shortly
            # after today. Must not raise here — dequeue_job() is the sync, non-awaited removal
            # API and its callers cannot handle a spawn rejection.
            # See TaskBucketSealedError for why this is caught rather than pre-checked via
            # is_sealed; Scheduler.remove_job() is one of the cross-thread callers that motivates it.
            self.logger.debug("Task bucket sealed, skipping guard release for job %r", job.name)
        return removed_from_heap

    async def remove_job(self, job: "Job", *, detach_self: bool = False) -> bool:
        """Awaited entry point for the unified removal operation.

        Used where the caller must observe the guard-release/persistence tail complete
        before proceeding: destructive replacement (``if_exists="replace"``, which must
        await the old job's ``removed_at`` write landing before issuing the new
        registration's upsert against the same natural-key row — see
        ``Scheduler._add_job()``), registration rollback (``_rollback_failed_registration``),
        and owner cleanup (``remove_jobs()``, which awaits this per job).

        Not to be confused with ``_ScheduledJobQueue.remove_job``, which only touches the
        heap under its own lock.

        Args:
            job: The job to remove.
            detach_self: Passed by destructive replacement so a job replacing itself from its own
                callback keeps running — see ``_finish_removal``.

        Returns:
            True if the job was found and removed from the heap, False otherwise.
        """
        removed_from_heap = self._remove_from_live_state(job)
        await self._finish_removal(job, detach_self=detach_self)
        return removed_from_heap

    async def mark_job_removed(self, db_id: int) -> None:
        """Persist durable removal state for a job registration.

        Delegates to ``CommandExecutor.mark_job_removed``, which sets the ``removed_at``
        column — this method's name reflects the removal terminology used by the public
        API (``Job.remove()``, ``Scheduler.remove_job()``). No-op when ``db_id`` is None.

        Args:
            db_id: The ``id`` of the ``scheduled_jobs`` row to mark as removed.
        """
        await self._executor.mark_job_removed(db_id)

    def deregister_job(self, job: "Job") -> None:
        """Identity-checked removal of ``job`` from the live registry (``_jobs_by_id``).

        No-op when ``job`` has no ``db_id`` yet, or when the registry slot for its ``db_id``
        holds a different object — a crash-restart cycle can leave an orphaned ``Job`` sharing
        a ``db_id`` with a freshly re-registered live job (the upsert reuses the natural-key
        row), so an unconditional pop keyed on ``db_id`` alone could silently unregister the
        live job.

        Args:
            job: The job to remove from the registry.
        """
        if job.db_id is not None and self._jobs_by_id.get(job.db_id) is job:
            del self._jobs_by_id[job.db_id]

    def remove_jobs(self, jobs: "list[Job]") -> asyncio.Future[None]:
        """Remove exactly the given live jobs: heap, registry, guard, and persistence.

        Used by ``Scheduler.remove_all_jobs()`` for owner cleanup — the per-app ``Scheduler``
        already holds its owned jobs in ``_jobs_by_name``, including waiting, completed, and
        manual jobs that were never on the heap, so this targets exactly those objects instead
        of scanning the full registry by owner string, which would only reach heap-resident
        jobs.

        Spawned on this service's own ``task_bucket`` (not the caller's) so the removal writes
        survive the caller resource's own shutdown/cancellation window — the same reasoning as
        ``remove_job()``'s ``mark_job_removed`` spawn.

        When that bucket is already sealed (reachable only after a force-terminal teardown,
        which seals without running hooks), the rejection is absorbed rather than raised: every
        job's live state is still removed inline (registry, heap, removal callbacks), the
        guard-release/persistence tail is skipped exactly as ``dequeue_job()`` skips it, and an
        already-completed future is returned so awaiting callers on the shutdown path
        (``Scheduler.remove_all_jobs()``) proceed normally. Only that sealed rejection is
        absorbed — any other ``spawn()`` failure still propagates.

        Args:
            jobs: The jobs to remove.

        Returns:
            The spawned removal task, or an already-completed future when the bucket is sealed.
            Callers should only await the result.
        """
        try:
            return self.task_bucket.spawn(self._remove_jobs(jobs), name="scheduler:remove_jobs")
        except TaskBucketSealedError:
            # Same accepted force-terminal gap as dequeue_job(): guards stay unreleased and
            # removed_at is never persisted for these jobs. Caught at the spawn boundary rather
            # than pre-checked via is_sealed — see TaskBucketSealedError.
            self.logger.debug("Task bucket sealed, removing %d job(s) from live state only", len(jobs))
            for job in jobs:
                self._remove_from_live_state(job)
            # Constructing a future and resolving it before anything is attached schedules no
            # loop callbacks, so this is safe from a worker-thread caller (SyncScheduler).
            done: asyncio.Future[None] = self.hassette.loop.create_future()
            done.set_result(None)
            return done

    async def _remove_jobs(self, jobs: "list[Job]") -> None:
        """Async body for ``remove_jobs()``: removes each job via the unified removal
        operation (``remove_job()``) — see that method for the removal contract.
        """
        for job in jobs:
            await self.remove_job(job)

    def submit_job(self, job: "Job") -> None:
        """Submit one manual invocation of ``job``. Fire-and-observe: returns immediately.

        Confirms ``job.db_id`` still maps to the same live object in ``_jobs_by_id`` — an
        identity check, not just a key lookup, for the same crash-restart orphan-collision
        reason ``deregister_job()`` documents — then spawns
        ``run_job_with_guard(job, trigger_mode="manual")`` on this service's ``task_bucket``.

        Does not inspect or mutate schedule status, timing, trigger, or predicate, and does
        not preflight ``single`` mode or queue capacity: the job's existing
        ``ExecutionModeGuard`` and telemetry decide suppression, queuing, or dropping exactly
        as they do for an automatic dispatch. Manual submission never touches the job's
        automatic schedule — a pending one-shot or recurring occurrence still fires at its
        own time.

        Args:
            job: The job to submit for manual invocation.

        Raises:
            JobRemovedError: When ``job.db_id`` is ``None`` (never registered) or no longer
                maps to this same live object in the registry (the registration was removed
                — via ``Job.remove()``, ``Scheduler.remove_job()``/``remove_group()``, owner
                shutdown, or ``if_exists="replace"`` — after the caller obtained its handle).
            TaskBucketSealedError: When this service's task bucket is sealed (only after a
                force-terminal teardown). Propagated rather than absorbed: unlike removal, a
                submission is new work, so a rejected one must not look accepted. Not translated
                to ``JobRemovedError`` because the registration is still live — the service
                itself is what can no longer run work.
        """
        if job.db_id is None or self._jobs_by_id.get(job.db_id) is not job:
            raise JobRemovedError(job.name, job.db_id)

        self.task_bucket.spawn(
            self.run_job_with_guard(job, trigger_mode="manual"),
            name="scheduler:manual_trigger",
        )
