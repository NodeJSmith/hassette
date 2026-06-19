"""Unit tests for ExecutionModeGuard — the four-mode overlap state machine."""

import asyncio

from hassette.execution_mode import DEFAULT_QUEUE_DEPTH, ExecutionModeGuard, Outcome
from hassette.types.enums import ExecutionMode


class Tracker:
    """Spawns gated handler invocations and records concurrency for assertions.

    Each invocation waits on a shared ``gate`` event before completing, so a test can
    hold one or more invocations "running" while firing further triggers. ``running``
    counts currently-executing invocations; ``max_concurrent`` records the high-water mark.
    """

    def __init__(self, gate: asyncio.Event) -> None:
        self.gate = gate
        self.running = 0
        self.max_concurrent = 0
        self.completed = 0
        self.cancelled = 0
        self.started = 0
        self.run_order: list[int] = []

    def make_run_and_track(self, label: int = 0):
        """Return a run-and-track callable that spawns one gated invocation as a task."""

        async def invocation() -> None:
            self.started += 1
            self.running += 1
            self.max_concurrent = max(self.max_concurrent, self.running)
            try:
                await self.gate.wait()
                self.run_order.append(label)
                self.completed += 1
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
            finally:
                self.running -= 1

        def run_and_track() -> asyncio.Task:
            return asyncio.create_task(invocation())

        return run_and_track


async def settle() -> None:
    """Yield control a few times so spawned tasks reach their gate."""
    for _ in range(5):
        await asyncio.sleep(0)


class TestSingleMode:
    async def test_second_trigger_suppressed_while_first_runs(self) -> None:
        """A re-fire during a running invocation is dropped; suppressed increments."""
        gate = asyncio.Event()
        tracker = Tracker(gate)
        guard = ExecutionModeGuard(ExecutionMode.SINGLE)

        first = await guard.run(tracker.make_run_and_track())
        await settle()
        assert first is Outcome.RAN

        second = await guard.run(tracker.make_run_and_track())
        assert second is Outcome.SUPPRESSED
        assert guard.suppressed == 1

        gate.set()
        await settle()
        assert tracker.started == 1
        assert tracker.completed == 1

    async def test_runs_again_after_first_completes(self) -> None:
        """A single guard accepts a new invocation once the prior one finishes."""
        gate = asyncio.Event()
        tracker = Tracker(gate)
        guard = ExecutionModeGuard(ExecutionMode.SINGLE)

        await guard.run(tracker.make_run_and_track())
        gate.set()
        await settle()

        gate2 = asyncio.Event()
        gate2.set()
        tracker2 = Tracker(gate2)
        outcome = await guard.run(tracker2.make_run_and_track())
        await settle()
        assert outcome is Outcome.RAN
        assert tracker2.completed == 1
        assert guard.suppressed == 0


class TestRestartMode:
    async def test_second_trigger_cancels_first(self) -> None:
        """A re-fire cancels the running invocation; the new one runs to completion."""
        gate = asyncio.Event()
        tracker = Tracker(gate)
        guard = ExecutionModeGuard(ExecutionMode.RESTART)

        await guard.run(tracker.make_run_and_track(label=1))
        await settle()
        assert tracker.running == 1

        # Second trigger: must cancel the first and start the second.
        await guard.run(tracker.make_run_and_track(label=2))
        await settle()

        assert tracker.cancelled == 1  # first invocation observed CancelledError
        assert tracker.running == 1  # exactly the replacement running now

        gate.set()
        await settle()
        assert tracker.completed == 1
        assert tracker.run_order == [2]

    async def test_no_exception_escapes_on_cancel(self) -> None:
        """The cancellation of the prior invocation does not propagate out of the guard."""
        gate = asyncio.Event()
        tracker = Tracker(gate)
        guard = ExecutionModeGuard(ExecutionMode.RESTART)

        await guard.run(tracker.make_run_and_track())
        await settle()
        # If the cancel leaked, this await would raise.
        await guard.run(tracker.make_run_and_track())
        await settle()
        gate.set()
        await settle()

    async def test_rapid_abc_never_two_concurrent(self) -> None:
        """A->B->C in tight succession never runs two invocations concurrently."""
        gate = asyncio.Event()
        tracker = Tracker(gate)
        guard = ExecutionModeGuard(ExecutionMode.RESTART)

        await asyncio.gather(
            guard.run(tracker.make_run_and_track(label=1)),
            guard.run(tracker.make_run_and_track(label=2)),
            guard.run(tracker.make_run_and_track(label=3)),
        )
        await settle()

        assert tracker.max_concurrent == 1

        gate.set()
        await settle()
        assert tracker.running == 0
        assert tracker.completed == 1  # only the survivor completed


class TestQueuedMode:
    async def test_triggers_run_in_arrival_order(self) -> None:
        """Triggers during a run execute in arrival order, one at a time."""
        gate = asyncio.Event()
        tracker = Tracker(gate)
        guard = ExecutionModeGuard(ExecutionMode.QUEUED)

        await guard.run(tracker.make_run_and_track(label=1))
        await settle()
        await guard.run(tracker.make_run_and_track(label=2))
        await guard.run(tracker.make_run_and_track(label=3))
        await settle()

        # Only the first is running; the rest are queued.
        assert tracker.max_concurrent == 1

        # Open the gate permanently so each drained invocation completes immediately.
        gate.set()
        await settle()

        assert tracker.run_order == [1, 2, 3]
        assert tracker.max_concurrent == 1
        assert guard.dropped == 0

    async def test_cap_drops_newest_preserves_queue(self) -> None:
        """At cap, the newest trigger is dropped; the existing queue is preserved."""
        gate = asyncio.Event()
        tracker = Tracker(gate)
        guard = ExecutionModeGuard(ExecutionMode.QUEUED, cap=2)

        await guard.run(tracker.make_run_and_track(label=0))  # running
        await settle()

        a = await guard.run(tracker.make_run_and_track(label=1))  # queued (1/2)
        b = await guard.run(tracker.make_run_and_track(label=2))  # queued (2/2 — at cap)
        c = await guard.run(tracker.make_run_and_track(label=3))  # dropped (newest)

        assert a is Outcome.QUEUED_ACCEPTED
        assert b is Outcome.QUEUED_ACCEPTED
        assert c is Outcome.DROPPED
        assert guard.dropped == 1

        gate.set()
        await settle()
        # Running invocation + two preserved queue entries ran; the newest never did.
        assert tracker.run_order == [0, 1, 2]

    async def test_failed_queued_factory_does_not_strand_queue(self) -> None:
        """A factory that raises synchronously during drain is dropped; the rest of the queue runs."""
        gate = asyncio.Event()
        tracker = Tracker(gate)
        guard = ExecutionModeGuard(ExecutionMode.QUEUED)

        def boom() -> asyncio.Task:
            raise RuntimeError("spawn failed")

        await guard.run(tracker.make_run_and_track(label=0))  # running
        await settle()
        await guard.run(boom)  # queued, but will raise when drained
        await guard.run(tracker.make_run_and_track(label=1))  # queued behind the bad one

        gate.set()
        await settle()

        # The failed factory was dropped and draining continued to the good one.
        assert tracker.run_order == [0, 1]
        assert len(guard.pending) == 0
        assert guard.current_task is None


class TestParallelMode:
    async def test_concurrent_invocations(self) -> None:
        """Parallel mode runs M triggers concurrently (pass-through)."""
        gate = asyncio.Event()
        tracker = Tracker(gate)
        guard = ExecutionModeGuard(ExecutionMode.PARALLEL)

        for _ in range(4):
            outcome = await guard.run(tracker.make_run_and_track())
            assert outcome is Outcome.RAN
        await settle()

        assert tracker.max_concurrent == 4
        assert tracker.running == 4

        gate.set()
        await settle()
        assert tracker.completed == 4


class TestRelease:
    async def test_release_cancels_running_and_clears_queue(self) -> None:
        """release() cancels the tracked task and drops pending queued factories."""
        gate = asyncio.Event()
        tracker = Tracker(gate)
        guard = ExecutionModeGuard(ExecutionMode.QUEUED, cap=DEFAULT_QUEUE_DEPTH)

        await guard.run(tracker.make_run_and_track(label=0))  # running
        await settle()
        await guard.run(tracker.make_run_and_track(label=1))  # queued
        await guard.run(tracker.make_run_and_track(label=2))  # queued

        await guard.release()
        await settle()

        assert tracker.cancelled == 1  # the running invocation was cancelled
        assert tracker.completed == 0  # neither queued factory ran
        assert tracker.started == 1  # queued factories were never spawned
        assert len(guard.pending) == 0  # no references retained
        assert guard.current_task is None

        # Even after settling further, the queued factories never run.
        gate.set()
        await settle()
        assert tracker.started == 1
        assert tracker.completed == 0
