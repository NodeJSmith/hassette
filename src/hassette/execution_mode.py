"""The shared overlap state machine for event-handler (and, later, scheduler) execution.

``ExecutionModeGuard`` owns the four-mode overlap behavior — ``single``, ``restart``,
``queued``, ``parallel`` — for one listener. It is overlap-only: it does no I/O, holds no
telemetry beyond two live counters, and never spawns a detached task. The caller supplies a
"run-and-track" callable that spawns one handler invocation through the caller's own task
machinery; the guard decides whether and when to call it, retains the returned task as the
cancellable handle, and (for ``queued``) drains pending factories one at a time.

The scheduler follow-up (#1027) reuses this module unchanged.
"""

import asyncio
from collections import deque
from collections.abc import Callable
from logging import getLogger
from typing import Final

from hassette.types.enums import ExecutionMode, Outcome

LOGGER = getLogger(__name__)

DEFAULT_QUEUE_DEPTH = 10
"""Maximum number of pending invocations held for a ``queued`` listener (matching Home Assistant).

Passed to the guard's constructor so a future ``max`` parameter overrides the value with no
change to the guard's shape.
"""

RunAndTrack = Callable[[], "asyncio.Task[None]"]
"""A caller-supplied callable that spawns one handler invocation and returns its task."""


class ExecutionModeGuard:
    """Per-listener overlap state machine for the four execution modes.

    One instance exists per listener. The guard tracks at most one running invocation for
    ``single``/``restart``/``queued`` and serializes its critical section with an internal lock
    so concurrently-spawned dispatch tasks cannot interleave a ``restart`` cancel-and-replace.
    ``parallel`` is a pass-through with no tracking or locking.
    """

    __slots__ = ("_cap", "_lock", "_mode", "current_task", "dropped", "pending", "suppressed")

    def __init__(self, mode: ExecutionMode, cap: int = DEFAULT_QUEUE_DEPTH) -> None:
        self._mode: Final[ExecutionMode] = mode
        self._cap = cap
        self._lock = asyncio.Lock()
        self.current_task: asyncio.Task[None] | None = None
        # Logically bounded to ``_cap`` via the explicit length check in ``_run_queued``, NOT via
        # ``deque(maxlen=_cap)``: a maxlen deque evicts the OLDEST (leftmost) entry on overflow,
        # but the spec requires dropping the NEWEST trigger. Do not replace with ``maxlen``.
        self.pending: deque[RunAndTrack] = deque()
        self.suppressed = 0
        self.dropped = 0

    async def run(self, run_and_track: RunAndTrack) -> Outcome:
        """Apply the listener's mode to one trigger.

        ``run_and_track`` spawns a fresh handler-invocation task and returns it. The guard never
        spawns the task itself — it only decides whether and when to call this callable.
        """
        if self._mode is ExecutionMode.PARALLEL:
            run_and_track()
            return Outcome.RAN

        async with self._lock:
            if self._mode is ExecutionMode.SINGLE:
                return self._run_single(run_and_track)
            if self._mode is ExecutionMode.RESTART:
                return await self._run_restart(run_and_track)
            return self._run_queued(run_and_track)

    def _run_single(self, run_and_track: RunAndTrack) -> Outcome:
        if self._is_running():
            self.suppressed += 1
            LOGGER.debug("single-mode listener busy; suppressing re-fire (suppressed=%d)", self.suppressed)
            return Outcome.SUPPRESSED
        self.current_task = run_and_track()
        return Outcome.RAN

    async def _run_restart(self, run_and_track: RunAndTrack) -> Outcome:
        task = self.current_task
        if task is not None and not task.done():
            task.cancel()
            # gather(return_exceptions=True) captures the child's CancelledError as a result rather
            # than propagating it into this awaiting coroutine — the lock stays held throughout so no
            # third trigger interleaves the cancel-and-replace (FR#13).
            await asyncio.gather(task, return_exceptions=True)
        self.current_task = run_and_track()
        return Outcome.RAN

    def _run_queued(self, run_and_track: RunAndTrack) -> Outcome:
        if self._is_running():
            if len(self.pending) >= self._cap:
                self.dropped += 1
                LOGGER.debug("queued listener at cap=%d; dropping newest trigger (dropped=%d)", self._cap, self.dropped)
                return Outcome.DROPPED
            self.pending.append(run_and_track)
            return Outcome.QUEUED_ACCEPTED
        self._start_queued(run_and_track)
        return Outcome.RAN

    def _start_queued(self, run_and_track: RunAndTrack) -> None:
        """Spawn a queued invocation and arrange to drain the next factory when it completes."""
        task = run_and_track()
        self.current_task = task
        task.add_done_callback(self._drain_next)

    def _drain_next(self, _done: "asyncio.Task[None]") -> None:
        """Done-callback: start the next queued factory, one at a time, in arrival order.

        Runs without the lock: asyncio invokes done-callbacks on the single event-loop thread, so
        ``current_task``/``pending`` access here cannot race the lock-held paths in ``run`` —
        adding a lock would deadlock (the callback fires synchronously from task completion).
        """
        # ``release()`` clears ``pending`` and detaches ``current_task``; if it ran, drain nothing.
        if self.current_task is not _done:
            return
        self.current_task = None
        # Drain in arrival order. If a factory raises synchronously, drop it and try the next so a
        # single failed spawn cannot strand the rest of the queue with no live task to re-trigger it.
        while self.pending:
            run_and_track = self.pending.popleft()
            try:
                task = run_and_track()
            except Exception:
                LOGGER.exception("queued invocation failed to start; dropping it and draining the next")
                continue
            self.current_task = task
            task.add_done_callback(self._drain_next)
            return

    def _is_running(self) -> bool:
        return self.current_task is not None and not self.current_task.done()

    async def release(self) -> None:
        """Cancel the tracked task and drop all pending factories, retaining no references.

        Called when a listener is cancelled or re-registered. Pending ``queued`` factories are
        discarded rather than run, even when ``release`` is called mid-drain.
        """
        async with self._lock:
            self.pending.clear()
            task = self.current_task
            self.current_task = None
            if task is None or task.done():
                return
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
