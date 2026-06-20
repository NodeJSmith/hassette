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
from collections.abc import Awaitable, Callable
from logging import getLogger
from typing import Final

from hassette.types.enums import ExecutionMode, Outcome

LOGGER = getLogger(__name__)

DEFAULT_QUEUE_DEPTH = 10
"""Maximum number of pending invocations held for a ``queued`` listener (matching Home Assistant).

Passed to the guard's constructor so a future ``max`` parameter overrides the value with no
change to the guard's shape.
"""

STALL_THRESHOLD_SECONDS: float = 60.0
"""Single source of truth. Imported by both subsystems and passed explicitly as
``threshold=`` at each call site — never used as a helper default argument (a
default binds at definition time and would defeat test patches)."""

RunAndTrack = Callable[[], "asyncio.Task[None]"]
"""A caller-supplied callable that spawns one handler invocation and returns its task."""


class ExecutionModeGuard:
    """Per-listener overlap state machine for the four execution modes.

    One instance exists per listener. The guard tracks at most one running invocation for
    ``single``/``restart``/``queued`` and serializes its critical section with an internal lock
    so concurrently-spawned dispatch tasks cannot interleave a ``restart`` cancel-and-replace.

    ``parallel`` is a fire-and-forget pass-through: ``run()`` calls ``run_and_track()`` and
    discards the returned task. The spawned task is owned and tracked by the caller's own task
    machinery (the bus's ``task_bucket``) — the guard neither retains nor awaits it, holds no
    tracking state, and takes no lock. A caller that needs to await the handler must not route a
    parallel listener through ``run()``; ``HandlerInvoker`` awaits parallel inline and never
    reaches this branch.
    """

    __slots__ = ("_cap", "_lock", "_mode", "current_task", "dropped", "pending", "suppressed")

    def __init__(self, mode: ExecutionMode, cap: int = DEFAULT_QUEUE_DEPTH) -> None:
        self._mode: Final[ExecutionMode] = mode
        self._cap = cap
        self._lock = asyncio.Lock()
        self.current_task: asyncio.Task[None] | None = None
        # Logically bounded to ``_cap`` via the explicit length check in ``run_queued``, NOT via
        # ``deque(maxlen=_cap)``: a maxlen deque evicts the OLDEST (leftmost) entry on overflow,
        # but the spec requires dropping the NEWEST trigger. Do not replace with ``maxlen``.
        self.pending: deque[RunAndTrack] = deque()
        self.suppressed = 0
        self.dropped = 0

    async def run(self, run_and_track: RunAndTrack) -> Outcome:
        """Apply the listener's mode to one trigger.

        ``run_and_track`` spawns a fresh handler-invocation task and returns it. For
        ``single``/``restart``/``queued`` the guard decides whether and when to call this
        callable and retains the returned task as its cancellable handle. For ``parallel`` the
        guard calls it once and discards the returned task — the task is owned and tracked by the
        caller's task machinery, not by the guard. A caller needing to await the handler must not
        route a parallel listener here.
        """
        if self._mode is ExecutionMode.PARALLEL:
            run_and_track()  # fire-and-forget: caller's task_bucket tracks it; parallel does not await
            return Outcome.RAN

        async with self._lock:
            if self._mode is ExecutionMode.SINGLE:
                return self.run_single(run_and_track)
            if self._mode is ExecutionMode.RESTART:
                return await self.run_restart(run_and_track)
            return self.run_queued(run_and_track)

    def run_single(self, run_and_track: RunAndTrack) -> Outcome:
        if self.is_running():
            self.suppressed += 1
            LOGGER.debug("single-mode listener busy; suppressing re-fire (suppressed=%d)", self.suppressed)
            return Outcome.SUPPRESSED
        self.current_task = run_and_track()
        return Outcome.RAN

    async def run_restart(self, run_and_track: RunAndTrack) -> Outcome:
        task = self.current_task
        if task is not None and not task.done():
            task.cancel()
            # gather(return_exceptions=True) captures the child's CancelledError as a result rather
            # than propagating it into this awaiting coroutine — the lock stays held throughout so no
            # third trigger interleaves the cancel-and-replace.
            await asyncio.gather(task, return_exceptions=True)
        self.current_task = run_and_track()
        return Outcome.RAN

    def run_queued(self, run_and_track: RunAndTrack) -> Outcome:
        if self.is_running():
            if len(self.pending) >= self._cap:
                self.dropped += 1
                LOGGER.debug("queued listener at cap=%d; dropping newest trigger (dropped=%d)", self._cap, self.dropped)
                return Outcome.DROPPED
            self.pending.append(run_and_track)
            return Outcome.QUEUED_ACCEPTED
        self.start_queued(run_and_track)
        return Outcome.RAN

    def start_queued(self, run_and_track: RunAndTrack) -> None:
        """Spawn a queued invocation and arrange to drain the next factory when it completes."""
        task = run_and_track()
        self.current_task = task
        task.add_done_callback(self.drain_next)

    def drain_next(self, _done: "asyncio.Task[None]") -> None:
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
            task.add_done_callback(self.drain_next)
            return

    def is_running(self) -> bool:
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


async def run_with_stall_watch(
    invoke: Callable[[], Awaitable[None]],
    warn: Callable[[float], None],
    threshold: float,
) -> None:
    """Run one invocation; call ``warn(threshold)`` if it holds past ``threshold`` seconds.

    ``warn`` receives the same ``threshold`` the watchdog armed at, so a logged stall
    message can never disagree with when the watchdog fired.
    """
    watchdog = asyncio.get_running_loop().call_later(threshold, warn, threshold)
    try:
        await invoke()
    finally:
        watchdog.cancel()


async def run_through_guard(
    guard: ExecutionModeGuard,
    spawn: Callable[..., "asyncio.Task[None]"],
    pending_done: "set[asyncio.Future[None]]",
    invoke: Callable[[], Awaitable[None]],
    warn: Callable[[float], None],
    spawn_name: str,
    threshold: float,
) -> None:
    """Route one non-parallel invocation through ``guard``, bridging completion via a future.

    Caller handles the ``parallel`` fast-path first — this is the single/restart/queued
    path only. Installs exactly one done-callback on ``pending_done`` per call; that
    callback fires when the spawned task completes, which may be after this function
    returns. Caller must call ``drain_pending_done(pending_done)`` after every
    ``guard.release()`` to resolve futures whose factory was dropped without running.

    Note: the ``drain_next``/``release`` interleave edge (a task spawned by ``drain_next``
    concurrently with ``release()`` may detach rather than cancel) applies to every caller
    that reaches release through a detached spawn — both the bus and the scheduler. Not
    fixed here; tracked in issue #1099.
    """
    loop = asyncio.get_running_loop()
    done: asyncio.Future[None] = loop.create_future()
    pending_done.add(done)

    def resolve_done() -> None:
        pending_done.discard(done)
        if not done.done():
            done.set_result(None)

    def run_and_track() -> "asyncio.Task[None]":
        task = spawn(run_with_stall_watch(invoke, warn, threshold), name=spawn_name)
        task.add_done_callback(lambda _t: resolve_done())
        return task

    outcome = await guard.run(run_and_track)
    if outcome in (Outcome.SUPPRESSED, Outcome.DROPPED):
        resolve_done()
        return
    await done


def drain_pending_done(pending_done: "set[asyncio.Future[None]]") -> None:
    """Resolve every unresolved completion future. Call after ``guard.release()``."""
    for done in list(pending_done):
        pending_done.discard(done)
        if not done.done():
            done.set_result(None)
