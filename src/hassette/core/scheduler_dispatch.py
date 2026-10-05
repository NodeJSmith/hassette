import asyncio
import logging
import random
import time
import traceback
import typing

import uuid_utils
from hassette_wire import ExecutionMode, ExecutionStatus, ScheduleStatus, ScheduleStatusReason
from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.commands import ExecuteJob
from hassette.core.execution_record import ExecutionRecord
from hassette.execution_mode import STALL_THRESHOLD_SECONDS, run_through_guard
from hassette.scheduler.classes import Job
from hassette.scheduler.error_context import SchedulerErrorContext
from hassette.scheduler.triggers import _WaitingSentinel

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.command_executor import CommandExecutor
    from hassette.scheduler.job_queue import _ScheduledJobQueue
    from hassette.task_bucket.task_bucket import TaskBucket


class SchedulerDispatchMixin:
    """Dispatch pipeline for ``SchedulerService``: get a job onto the heap and run it when due."""

    hassette: "Hassette"
    logger: logging.Logger
    task_bucket: "TaskBucket"
    _executor: "CommandExecutor"
    _job_queue: "_ScheduledJobQueue"
    _wakeup_event: asyncio.Event

    def kick(self) -> None:
        self._wakeup_event.set()

    async def enqueue_job(self, job: "Job") -> None:
        """Push a job onto the queue and wake the scheduler."""
        self.apply_jitter_to_heap(job)
        await self._job_queue.add(job)
        self.kick()

    async def reschedule_job(self, job: "Job", result: "ZonedDateTime | _WaitingSentinel") -> None:
        """Move a registered EntityTime job to a new concrete time, or to/from WAITING.

        Unlike ``dequeue_job``/``_remove_jobs``, no removal callbacks fire and the job keeps
        its ``db_id`` — it stays a registered job that either moves to a different slot on
        the heap, activates onto the heap from ``WAITING``, or leaves the heap for
        ``WAITING``. Used by ``Scheduler`` when an entity-driven trigger's source entity
        changes.

        Only attempts heap removal when ``job.schedule_status is ScheduleStatus.SCHEDULED``
        — a job in any other status (most commonly ``WAITING``) is never on the heap, and a
        job that has never been ``SCHEDULED`` has no ``sort_index`` at all (the dataclass
        field is ``init=False`` with no default, only assigned by ``set_next_run``), so an
        unconditional heap-removal attempt would raise ``AttributeError`` comparing it.

        A ``SCHEDULED`` job not found on the heap is being dispatched for its own due fire
        right now — the transition is stored as pending so ``dispatch_and_log`` can apply it
        after that fire completes, instead of enqueuing the same job twice. A ``SCHEDULED``
        job found on the heap, or a job in any other status, applies the transition
        immediately since there is no in-flight dispatch to race. Every transition applied
        here is persisted via ``persist_schedule_status`` immediately after
        ``transition_to()``, same as ``dispatch_and_log`` — a pending transition (stored for
        ``dispatch_and_log`` to apply later) is not persisted here since no transition has
        happened yet; ``dispatch_and_log`` persists it when it applies the stored result.

        Args:
            job: The job to move.
            result: The new logical fire time, or ``WAITING`` when the entity has no usable
                time right now.
        """
        if job._dequeued:
            return

        if job.schedule_status is ScheduleStatus.SCHEDULED:
            removed_from_heap = await self._job_queue.remove_job(job)
            if not removed_from_heap:
                job._pending_entity_time_transition = result
                self.logger.debug("Job %s mid-dispatch; stored pending transition to %s", job, result)
                return

        if isinstance(result, _WaitingSentinel):
            job.transition_to(ScheduleStatus.WAITING)
            await self.persist_schedule_status(job)
            self.logger.debug("Job %s moved to waiting (entity has no usable time)", job)
            return

        job.transition_to(ScheduleStatus.SCHEDULED, next_run=result)
        await self.persist_schedule_status(job)
        await self.enqueue_job(job)
        self.logger.debug("Rescheduled job %s to %s", job, job.next_run)

    def apply_jitter_to_heap(self, job: "Job") -> None:
        """Apply jitter to the heap sort_index and fire_at without mutating job.next_run.

        If job.jitter is not None, a random offset in [0, jitter) seconds is added
        to ``job.fire_at`` and ``job.sort_index``. ``job.next_run`` is never modified
        — it is the unjittered logical fire time used as ``previous_run`` in subsequent
        trigger calls. When jitter is None or 0, ``fire_at`` equals ``next_run`` exactly
        (already set by ``set_next_run``).

        Args:
            job: The job whose sort_index and fire_at should be jittered.
        """
        if job.jitter is None:
            return
        # Only a SCHEDULED job is ever passed here (enqueue_job() is only reachable for
        # jobs with a concrete occurrence) — asserted rather than silently no-op'd so a
        # future caller violating that invariant fails loudly instead of corrupting the heap.
        assert job.next_run is not None, "apply_jitter_to_heap requires a job with a concrete next_run"

        offset = random.uniform(0, job.jitter)
        try:
            jittered_time = job.next_run.add(seconds=offset)
        except ValueError:
            jittered_time = job.next_run
        job.fire_at = jittered_time
        job.sort_index = (jittered_time.timestamp_nanos(), id(job))
        self.logger.debug(
            "Applied jitter offset=%.3fs to job %s: next_run=%s → fire_at=%s",
            offset,
            job,
            job.next_run,
            job.fire_at,
        )

    async def persist_schedule_status(self, job: "Job") -> None:
        """Persist ``job``'s current ``schedule_status``/``schedule_status_reason`` to the DB.

        Called after every ``Job.transition_to()`` call in ``dispatch_and_log`` and
        ``reschedule_job`` so a degraded (DB-only) response still reflects the job's true
        status when live enrichment is unavailable. No-op for a job with no ``db_id`` yet —
        an unregistered or degraded-registration job has no row to update.

        Args:
            job: The job whose current schedule status should be persisted.
        """
        if job.db_id is None:
            return
        await self._executor.mark_job_status(job.db_id, job.schedule_status, job.schedule_status_reason)

    async def dispatch_and_log(self, job: "Job") -> None:
        """Dispatch a job and log its execution.

        Ordering: skip-if-dequeued → compute next schedule status → (enqueue OR persist the
        new status) → predicate check → run-through-guard.

        The current due fire ALWAYS runs once popped, regardless of what the trigger
        produces. Computing the next occurrence happens first so a recurring job's next
        tick is on the heap before the current run completes, enabling overlap. A trigger
        that returns ``None``, returns ``WAITING``, or raises never removes the job's live
        registration — those outcomes only change ``schedule_status`` (to ``COMPLETED`` or
        ``WAITING``). The job stays addressable and submit-capable via ``_jobs_by_id`` until
        explicit removal (``Job.remove()``/``Scheduler.remove_job()``).

        Args:
            job: The job to dispatch.
        """
        if job._dequeued:
            self.logger.debug("Job %s was dequeued (cancelled between heap-pop and dispatch), skipping", job)
            return

        self.logger.debug("Dispatching job: %s", job)

        # Dispatch-local timing: the due occurrence's fire_at, captured before any transition
        # below can clear job.next_run/fire_at (COMPLETED and WAITING both wipe them). run_job()
        # falls back to this value for its lag calculation when the job's own fire_at has
        # already been cleared by the time it runs.
        dispatch_fire_at = job.fire_at

        # Step 1: Compute the next schedule status and either enqueue the next occurrence or
        # persist the new (non-heap) status. The current fire ALWAYS runs regardless of outcome.
        if job.trigger is not None:
            # Only a SCHEDULED job (concrete next_run) is ever popped for dispatch — the
            # due-time heap enforces this. Asserted rather than silently skipped so a future
            # caller violating that invariant fails loudly instead of dispatching bad state.
            assert job.next_run is not None, "dispatch_and_log requires a job with a concrete next_run"
            try:
                if job._pending_entity_time_transition is not None:
                    next_run = job._pending_entity_time_transition
                    job._pending_entity_time_transition = None
                else:
                    next_run = job.trigger.next_run_time(job.next_run, date_utils.now())
            except Exception:
                self.logger.exception(
                    "dispatch_and_log: trigger raised for db_id=%s callable=%s trigger=%r — "
                    "running current fire then completing job",
                    job.db_id,
                    getattr(job.job, "__qualname__", str(job.job)),
                    job.trigger,
                )
                job.transition_to(ScheduleStatus.COMPLETED, reason=ScheduleStatusReason.TRIGGER_ERROR)
                await self.persist_schedule_status(job)
            else:
                if isinstance(next_run, _WaitingSentinel):
                    # EntityTime's source has no usable time right now, mid-recurrence (the
                    # third WAITING leg — registration-time and reconciliation-time waiting
                    # are handled elsewhere). The job stays registered and watched, off the heap.
                    job.transition_to(ScheduleStatus.WAITING)
                    await self.persist_schedule_status(job)
                    self.logger.debug("Job %s has no usable next occurrence right now — waiting", job)
                elif next_run is not None:
                    curr_next_run = job.next_run
                    job.transition_to(ScheduleStatus.SCHEDULED, next_run=next_run)
                    assert job.next_run is not None
                    delta_to_now = (job.next_run - date_utils.now()).total("seconds")
                    if delta_to_now <= 0:
                        self.logger.warning(
                            "Trigger produced non-future next_run (%.3fs in the past), advancing by 1s",
                            -delta_to_now,
                        )
                        job.transition_to(ScheduleStatus.SCHEDULED, next_run=date_utils.now().add(seconds=1))
                    await self.persist_schedule_status(job)
                    self.logger.debug(
                        "Rescheduling repeating job %s from %s to %s",
                        job,
                        curr_next_run,
                        job.next_run,
                    )
                    # Enqueue next occurrence BEFORE running — enables overlap.
                    # The in-lock _dequeued re-check inside _job_queue.add guards
                    # against a cancel landing between here and the push.
                    await self.enqueue_job(job)
                    if job._pending_entity_time_transition is not None:
                        pending_transition = job._pending_entity_time_transition
                        job._pending_entity_time_transition = None
                        await self.reschedule_job(job, pending_transition)
                else:
                    # next_run_time() returned None — trigger exhausted normally. The job
                    # remains live and submit-capable; it just leaves the heap.
                    job.transition_to(ScheduleStatus.COMPLETED)
                    await self.persist_schedule_status(job)
        else:
            # No trigger, yet reached the heap — should never happen (manual-only jobs never
            # enqueue), but complete defensively rather than leaving stale SCHEDULED timing.
            job.transition_to(ScheduleStatus.COMPLETED)
            await self.persist_schedule_status(job)

        # A job that just transitioned away from SCHEDULED (COMPLETED via the trigger-raised,
        # trigger-exhausted, or no-trigger branch above, or WAITING via the mid-recurrence
        # branch) must not remain on the due-time heap. One check here — rather than a
        # removal call inlined at each of those four transition sites — because the condition
        # they all share is simply "did this dispatch leave the job off SCHEDULED", which is
        # cheaper and less error-prone to ask once than to repeat at each call site. The
        # recurring/re-enqueue branch is excluded because it leaves the job SCHEDULED with a
        # freshly pushed heap entry that must stay. `job.trigger is not None` excludes the
        # no-trigger branch for a different reason: a trigger-less job never reaches the heap
        # in the first place (manual-only jobs never call enqueue_job), so there is nothing to
        # remove — the check would be harmless either way, but this makes that explicit.
        #
        # Normally this call is a no-op: the serve loop already popped this job from the heap
        # before spawning dispatch_and_log. It only does real work when dispatch_and_log was
        # invoked directly on a job that is still heap-resident, as several tests in
        # tests/integration/test_scheduler.py do deliberately, to force a future occurrence to
        # fire early — e.g. run_in(delay=10) followed by an immediate
        # `await scheduler_service.dispatch_and_log(job)`. Without this cleanup, that job's
        # original heap entry survives with its next_run/fire_at wiped to None by the
        # COMPLETED/WAITING transition, corrupting the heap's sort order and crashing
        # pop_due_and_peek_next's `assert candidate.fire_at is not None` — see KI-006 in
        # design/specs/090-registered-manual-jobs/known-issues.md for the full incident.
        if job.trigger is not None and job.schedule_status is not ScheduleStatus.SCHEDULED:
            await self._job_queue.remove_job(job)

        # Step 2: Evaluate the job's predicate (if any) before running the handler.
        # This must come after step 1 (next occurrence computed/enqueued/status persisted) so
        # a skipped recurring job still continues its schedule, and before step 3
        # (guard/execution) so a skip never invokes the handler.
        if job.predicate is not None:
            predicate_start = time.time()
            try:
                kwargs = job.predicate_invoker.invoke({Job: job}) if job.predicate_invoker else {}
                should_run = job.predicate(**kwargs)
            except Exception as exc:
                self.logger.exception("Predicate raised for job %s — recording failure; the job does not run", job)
                self._record_predicate_failure(job, exc, predicate_start)
                return

            if not should_run:
                self.logger.debug("Predicate returned False for job %s — skipping", job)
                self._record_skipped(job)
                return

        # Step 3: Run the current due fire through the mode guard. dispatch_fire_at is a
        # fallback used only when the job's own fire_at was cleared above (COMPLETED/WAITING);
        # a still-SCHEDULED (recurring) job's own (already-updated) fire_at takes priority in
        # run_job(), matching existing behavior.
        try:
            await self.run_job_with_guard(job, fire_at=dispatch_fire_at)
        except asyncio.CancelledError:
            self.logger.debug("Dispatch cancelled for job %s", job)
            raise

    def _record_skipped(self, job: "Job") -> None:
        """Build and enqueue a 'skipped' ExecutionRecord for a job whose predicate returned False.

        Bypasses ``CommandExecutor._execute()``/``track_execution()`` entirely — a skip has no
        meaningful invocation to time. ``duration_ms=0.0`` marks it distinctly in duration
        aggregations (which exclude ``status='skipped'`` — see ``summary_queries.py``).

        Args:
            job: The job whose predicate returned False.
        """
        session_id = self.hassette.try_session_id()

        record = ExecutionRecord(
            kind="job",
            listener_id=None,
            job_id=job.db_id,
            session_id=session_id,
            execution_start_ts=time.time(),
            duration_ms=0.0,
            status=ExecutionStatus.SKIPPED,
            app_key=job.app_key,
            instance_index=job.instance_index,
            source_tier=job.source_tier,
            execution_id=str(uuid_utils.uuid7()),
        )
        self._executor.enqueue_record(record)

    def _record_predicate_failure(self, job: "Job", exc: Exception, start_ts: float) -> None:
        """Record a raising predicate as a failed execution and route it to error handlers.

        The handler never ran, so this bypasses ``CommandExecutor._execute()`` the same way
        ``_record_skipped`` does — but the outcome is an ``'error'`` record (with the real
        predicate-evaluation duration) so a broken predicate is visible in telemetry instead
        of vanishing into the task bucket's unhandled-exception log. The per-job ``on_error``
        handler (or the app-level fallback) is invoked with the same ``SchedulerErrorContext``
        a raising handler would produce.

        Args:
            job: The job whose predicate raised.
            exc: The exception the predicate raised.
            start_ts: Unix timestamp when predicate evaluation began.
        """
        session_id = self.hassette.try_session_id()

        traceback_str = "".join(traceback.format_exception(exc))
        execution_id = str(uuid_utils.uuid7())
        record = ExecutionRecord(
            kind="job",
            listener_id=None,
            job_id=job.db_id,
            session_id=session_id,
            execution_start_ts=start_ts,
            duration_ms=(time.time() - start_ts) * 1000,
            status=ExecutionStatus.ERROR,
            error_type=type(exc).__name__,
            error_message=str(exc),
            error_traceback=traceback_str,
            app_key=job.app_key,
            instance_index=job.instance_index,
            source_tier=job.source_tier,
            execution_id=execution_id,
        )
        self._executor.enqueue_record(record)

        app_level_error_handler = (
            job.app_error_handler_resolver() if job.app_error_handler_resolver is not None else None
        )
        error_handler = job.error_handler or app_level_error_handler
        if error_handler is not None:
            ctx = SchedulerErrorContext(
                exception=exc,
                traceback=traceback_str,
                execution_id=execution_id,
                job_name=job.name,
                job_group=job.group,
                args=job.args,
                kwargs=dict(job.kwargs),
            )
            self.task_bucket.spawn(
                self._executor.invoke_error_handler(error_handler, ctx),
                name="scheduler:predicate_error_handler",
            )

    async def run_job_with_guard(
        self, job: "Job", trigger_mode: str | None = None, fire_at: ZonedDateTime | None = None
    ) -> None:
        """Route one job invocation through the job's execution-mode guard.

        - ``parallel``: awaits ``run_job`` inline — concurrency comes from ``serve()``
          spawning a fresh dispatch task per due-pop. No stall watch, no guard state.
        - ``single``/``restart``/``queued``: delegates to ``run_through_guard``, which
          bridges completion via a per-invocation future and arms the stall watchdog.

        Args:
            job: The job to invoke.
            trigger_mode: How this execution was triggered (e.g., "manual" for a
                run-now request). None for regular scheduled fires.
            fire_at: Dispatch-local due time, forwarded to ``run_job`` for its lag
                calculation. See ``run_job``'s docstring for precedence against
                ``job.fire_at``.
        """
        if job.mode is ExecutionMode.PARALLEL:
            await self.run_job(job, trigger_mode=trigger_mode, fire_at=fire_at)
            return

        await run_through_guard(
            guard=job.guard,
            spawn=lambda coro, *, name: self.task_bucket.spawn(coro, name=name),
            pending_done=job.pending_done,
            invoke=lambda: self.run_job(job, trigger_mode=trigger_mode, fire_at=fire_at),
            warn=lambda secs: self.warn_stalled_job(job, secs),
            spawn_name="scheduler:mode_invocation",
            threshold=STALL_THRESHOLD_SECONDS,
        )

    def warn_stalled_job(self, job: "Job", threshold: float) -> None:
        """Emit the stall WARNING: a non-parallel job is still holding its guard.

        Called by the stall watchdog after ``threshold`` seconds. Named after the job
        and its mode so the operator can identify the stuck invocation.

        Args:
            job: The job whose invocation is stalled.
            threshold: The threshold the watchdog armed at, in seconds.
        """
        self.logger.warning(
            "Job '%s' has held its %s execution-mode guard for over %.0fs and is still running",
            job.name,
            job.mode.value,
            threshold,
        )

    async def run_job(self, job: "Job", trigger_mode: str | None = None, fire_at: ZonedDateTime | None = None) -> None:
        """Run a scheduled job by delegating to the CommandExecutor.

        All jobs go through ``ExecuteJob`` regardless of whether ``db_id`` is set.
        When ``db_id`` is ``None`` (job not yet registered), ``ExecuteJob`` is created
        with ``job_db_id=None`` and the ``CommandExecutor`` records an orphan execution row.

        Args:
            job: The job to run.
            trigger_mode: How this execution was triggered (e.g., "manual" for a
                run-now request). None for regular scheduled fires.
            fire_at: Dispatch-local fallback due time for the schedule-lag calculation.
                ``job.fire_at`` takes priority when set — a still-``SCHEDULED`` (recurring)
                job's own (already-updated) ``fire_at`` reflects existing behavior. This
                parameter only matters when ``job.fire_at`` has been cleared (a completing
                dispatch transitions the job to ``COMPLETED``/``WAITING`` before this runs),
                supplying the timing of the occurrence actually being dispatched. The lag
                calculation itself is gated on ``trigger_mode`` rather than on either timing
                value being set — a manually-submitted job (``trigger_mode="manual"``) may
                still have a concrete ``job.fire_at`` from a pending automatic occurrence
                (submission never mutates automatic schedule state), and attributing that
                unrelated schedule timing to the manual invocation would be a spurious
                "behind schedule" warning.
        """
        effective_fire_at = job.fire_at if job.fire_at is not None else fire_at
        if trigger_mode != "manual" and effective_fire_at is not None:
            lag = (date_utils.now() - effective_fire_at).total("seconds")
            if lag > self.hassette.config.scheduler.behind_schedule_threshold_seconds:
                self.logger.warning("Job %s is behind schedule by %.2fs", job, lag)

        async_fn = self.task_bucket.make_async_adapter(job.job)

        async def _bound_callable() -> None:
            await async_fn(*job.args, **job.kwargs)

        # Resolve effective timeout: timeout_disabled → None; job.timeout → use it;
        # job.timeout is None → config default
        if job.timeout_disabled:
            effective_timeout = None
        elif job.timeout is not None:
            effective_timeout = job.timeout
        else:
            effective_timeout = self.hassette.config.scheduler.job_timeout_seconds

        # Resolve the app-level error handler at dispatch time via the closure set by
        # Scheduler.add_job(). This avoids coupling the dispatch path to Scheduler internals.
        app_level_error_handler = (
            job.app_error_handler_resolver() if job.app_error_handler_resolver is not None else None
        )

        cmd = ExecuteJob(
            job=job,
            callable=_bound_callable,
            job_db_id=job.db_id,
            source_tier=job.source_tier,
            effective_timeout=effective_timeout,
            app_level_error_handler=app_level_error_handler,
            trigger_mode=trigger_mode,
        )
        await self._executor.execute(cmd)

    async def trigger_due_jobs(self) -> int:
        """Fire all jobs due at the current time.

        Snapshots due jobs via a single ``pop_due_and_peek_next(date_utils.now())``
        call, then awaits each ``dispatch_and_log(job)`` inline (not via
        ``task_bucket.spawn``). Jobs re-enqueued during dispatch (repeating jobs)
        are not included in this invocation — only the initial snapshot is
        processed, preventing infinite loops when the clock is frozen.

        For ``queued`` jobs that return ``QUEUED_ACCEPTED``, ``dispatch_and_log``
        blocks on the completion bridge until the queued invocation drains. Under a
        frozen clock this can deadlock when the drain callback fires synchronously
        within the same sequential loop. Tests that rely on ``queued`` multi-tick
        behavior must advance the loop with ``await asyncio.sleep(0)`` and assert
        via the guard state directly, rather than calling ``trigger_due_jobs`` twice
        back-to-back on the same blocked bridge.

        This method bypasses the ``serve()`` loop's timing and wakeup logic.
        Intended for controlled test dispatch via ``AppTestHarness.trigger_due_jobs()``
        or ``HassetteHarness.scheduler_service.trigger_due_jobs()``.

        Returns:
            The number of jobs dispatched.
        """
        current_time = date_utils.now()
        due_jobs, _next_run = await self._job_queue.pop_due_and_peek_next(current_time)

        count = 0
        for job in due_jobs:
            await self.dispatch_and_log(job)
            count += 1

        return count
