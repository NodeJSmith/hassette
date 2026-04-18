"""TimeControlMixin — time control helpers for AppTestHarness.

Contains ``freeze_time``, ``advance_time``, ``trigger_due_jobs``, ``_TestClock``,
and supporting helpers extracted from ``app_harness.py``.
"""

import contextlib
import logging
import threading
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import patch

from whenever import Instant, ZonedDateTime

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness

LOGGER = logging.getLogger(__name__)

# Process-local lock for freeze_time within this Python interpreter. Guards
# against overlapping freeze_time calls from multiple threads, and also from
# multiple asyncio coroutines running in the same process/event loop thread,
# because acquisition happens synchronously before patching time.
#
# Limitations: this lock does not coordinate across separate processes, is not
# re-entrant, and is not awaitable. Callers use a non-blocking acquire in
# synchronous code, so concurrent attempts fail immediately rather than waiting
# for the active freeze_time scope to finish.
_FREEZE_TIME_LOCK = threading.Lock()


class _TestClock:
    """Mutable test clock for controlling time in tests.

    Patches ``hassette.utils.date_utils.now`` to return a controlled time.
    Used internally by :meth:`AppTestHarness.freeze_time`.

    Not part of the public API — subject to change without notice.
    """

    _current: ZonedDateTime

    def __init__(self, instant: Instant | ZonedDateTime) -> None:
        """Initialize the clock at the given time.

        Args:
            instant: Starting time as an Instant or ZonedDateTime.
        """
        self._current = self._to_zoned(instant)

    @staticmethod
    def _to_zoned(instant: Instant | ZonedDateTime) -> ZonedDateTime:
        """Convert an Instant or ZonedDateTime to system-tz ZonedDateTime."""
        if isinstance(instant, ZonedDateTime):
            return instant
        return instant.to_system_tz()

    def current(self) -> ZonedDateTime:
        """Return the current frozen time.

        Returns:
            The current ZonedDateTime.
        """
        return self._current

    def set(self, instant: Instant | ZonedDateTime) -> None:
        """Set the clock to a new time.

        Args:
            instant: New time as an Instant or ZonedDateTime.
        """
        self._current = self._to_zoned(instant)

    def advance(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0) -> None:
        """Advance the clock by the given delta.

        Args:
            seconds: Seconds to advance.
            minutes: Minutes to advance.
            hours: Hours to advance.
        """
        self._current = self._current.add(seconds=seconds, minutes=minutes, hours=hours)


class TimeControlMixin:
    """Mixin providing time control helpers for ``AppTestHarness``.

    Depends on the host providing ``_harness``, ``_exit_stack``, and ``_require_harness``
    — declared as class-level annotations below, satisfied by ``AppTestHarness``.
    """

    # Provided by AppTestHarness; declared here for type narrowing within the mixin.
    _harness: "HassetteHarness | None"
    _exit_stack: AsyncExitStack | None

    # Provided via MRO by SimulationMixin when composed in AppTestHarness.
    def _require_harness(self) -> "HassetteHarness": ...

    # Single patch target for freeze_time. All production code accesses now() via
    # the module attribute (date_utils.now()), so patching the canonical source
    # is sufficient — no per-module patch list needed.
    _NOW_PATCH_TARGETS: ClassVar[tuple[str, ...]] = ("hassette.utils.date_utils.now",)

    def __init__(self) -> None:
        # Time control state (set by freeze_time). AppTestHarness.__init__ sets these
        # directly without calling super().__init__() — this __init__ exists only as a
        # safety net if TimeControlMixin is ever used standalone.
        self._test_clock: _TestClock | None = None
        self._time_patcher: list[object] | None = None
        self._time_patcher_registered: bool = False

    def _stop_time_patchers(self) -> None:
        """Stop all active time patchers. Called by exit stack on teardown."""
        if self._time_patcher is not None:
            for p in self._time_patcher:
                try:
                    p.stop()  # pyright: ignore[reportAttributeAccessIssue]
                except Exception:
                    LOGGER.warning("freeze_time: failed to stop patcher %s", p, exc_info=True)
            self._time_patcher = None

    def _release_freeze_time(self) -> None:
        """Stop time patchers and release the process-global freeze_time lock."""
        self._stop_time_patchers()
        with contextlib.suppress(RuntimeError):
            _FREEZE_TIME_LOCK.release()

    def freeze_time(self, instant: Instant | ZonedDateTime) -> None:
        """Freeze time at the given instant.

        Patches ``hassette.utils.date_utils.now`` to return the frozen time.
        Idempotent — calling again replaces the frozen time (stops old patchers first).

        The patchers are automatically stopped when the harness exits via the exit stack.
        A process-global lock prevents concurrent harnesses from silently corrupting
        each other's frozen clock. If another harness already holds the lock, a
        ``RuntimeError`` is raised immediately.

        Must be called inside ``async with AppTestHarness(...) as harness:`` — raises
        RuntimeError if called before entering the context manager.

        Args:
            instant: The time to freeze at, as an Instant or ZonedDateTime.

        Raises:
            RuntimeError: If called outside the async with block, or if another
                harness already holds the freeze_time lock.
        """
        if self._exit_stack is None:
            raise RuntimeError("freeze_time() must be called inside 'async with AppTestHarness(...) as harness:'.")

        # Acquire the process-global lock (non-blocking). Idempotent re-freeze
        # from the same harness is allowed (we already hold the lock).
        if self._time_patcher is None and not _FREEZE_TIME_LOCK.acquire(blocking=False):
            raise RuntimeError(
                "freeze_time is already held by another harness — "
                "time-controlling tests must be isolated (e.g., separate xdist workers)."
            )

        # Register teardown BEFORE starting patchers — if p.start() raises, the
        # lock is still released on exit. Only register once; subsequent freeze_time
        # calls reuse this callback.
        if not self._time_patcher_registered:
            self._exit_stack.callback(self._release_freeze_time)
            self._time_patcher_registered = True

        # Stop existing patchers if active (idempotent re-freeze)
        self._stop_time_patchers()

        clock = _TestClock(instant)
        self._test_clock = clock

        patchers: list[object] = []
        for target in self._NOW_PATCH_TARGETS:
            try:
                p = patch(target, side_effect=clock.current)
                p.start()
                patchers.append(p)
            except AttributeError:
                # Module may not import `now` — skip gracefully
                LOGGER.debug("freeze_time: could not patch %s (module does not import now)", target)

        self._time_patcher = patchers

    def advance_time(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0) -> None:
        """Advance frozen time by the given delta.

        Does NOT automatically trigger scheduled jobs — call :meth:`trigger_due_jobs`
        explicitly after advancing time.

        Args:
            seconds: Seconds to advance.
            minutes: Minutes to advance.
            hours: Hours to advance.

        Raises:
            RuntimeError: If :meth:`freeze_time` has not been called first.
        """
        if self._test_clock is None:
            raise RuntimeError(
                "advance_time() requires freeze_time() to be called first. "
                "Call harness.freeze_time(instant) before advancing time."
            )
        self._test_clock.advance(seconds=seconds, minutes=minutes, hours=hours)

    async def trigger_due_jobs(self) -> int:
        """Fire all jobs that are due at the current (possibly frozen) time.

        Delegates to :meth:`SchedulerService._test_trigger_due_jobs`, which
        snapshots due jobs and dispatches them inline. Jobs re-enqueued during
        dispatch (repeating jobs) are not included — only the initial snapshot
        is processed, preventing infinite loops when the clock is frozen.

        Note:
            This bypasses the scheduler's ``serve()`` loop — wakeup events and
            shutdown guards are not exercised. For testing the scheduler's own
            timing behavior, use the full harness with real time progression.

            If scheduled jobs send events through the bus, downstream handler
            tasks are spawned but not drained by this method. Call a
            ``simulate_*`` method or ``_drain_task_bucket`` afterward to ensure
            handler tasks complete before asserting on side effects.

        Returns:
            The number of jobs that were dispatched and completed.

        Raises:
            RuntimeError: If the harness is not active.
        """
        harness = self._require_harness()
        scheduler_service = harness.hassette._scheduler_service
        if scheduler_service is None:
            raise RuntimeError("SchedulerService is not available — ensure with_scheduler() was called")

        return await scheduler_service._test_trigger_due_jobs()
