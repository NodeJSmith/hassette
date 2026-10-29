"""Tests for shutdown propagation.

Verifies:
- shutdown() only executes once (double-call is a no-op)
- initialize() resets the flag so shutdown() works again
- initialize() clears shutdown_event
- start() resets the flag
- _finalize_shutdown() propagates shutdown to children in reverse insertion order
- Child shutdown errors are tolerated and logged
- Already-completed children are skipped
- Leaf Resources (no children) shut down normally
- Service subclasses inherit propagation
"""

import asyncio
import contextlib

import pytest
from hassette_wire import ResourceStatus

from hassette.exceptions import LifecycleReentryError, RestartRefusedError
from hassette.resources import lifecycle
from hassette.resources.base import Resource
from hassette.resources.lifecycle import start
from hassette.resources.operations import ordered_children_for_shutdown
from hassette.resources.shutdown_deadline import deadline_in
from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult, incomplete
from hassette.testing import wait_for
from tests.support.helpers import SHORT_SHUTDOWN_TIMEOUT_SECONDS
from tests.support.mock_hassette import make_mock_hassette
from tests.support.task_buckets import sealed_fallback_task_factory
from tests.unit.resources.conftest import ConcreteResource, wait_for_running

from .conftest import (
    ErrorChild,
    HangingChild,
    OrderTrackingChild,
    ShutdownCounter,
    SimpleParent,
    SimpleService,
    make_initialized_shutdown_counter,
    make_parent_with_child,
    shutdown_order,
)


async def test_shutdown_completed_prevents_double_shutdown():
    """Calling shutdown() twice only runs on_shutdown once."""
    resource = await make_initialized_shutdown_counter()

    await resource.shutdown()
    await resource.shutdown()  # second call should be a no-op

    assert resource.shutdown_count == 1, f"Expected 1 shutdown, got {resource.shutdown_count}"


async def test_shutdown_completed_reset_by_initialize():
    """After shutdown then initialize, shutdown() works again."""
    resource = await make_initialized_shutdown_counter()

    await resource.shutdown()
    assert resource.shutdown_count == 1

    await resource.initialize()
    await resource.shutdown()
    assert resource.shutdown_count == 2, f"Expected 2 shutdowns, got {resource.shutdown_count}"


async def test_shutdown_event_cleared_by_initialize():
    """initialize() clears shutdown_event so it is not set."""
    resource = await make_initialized_shutdown_counter()

    await resource.shutdown()
    assert resource.shutdown_event.is_set(), "shutdown_event should be set after shutdown"

    await resource.initialize()
    assert not resource.shutdown_event.is_set(), "shutdown_event should be cleared after initialize"


async def test_start_resets_shutdown_completed():
    """start() spawns a joiner task; once it runs, the coordinator resets shutdown_completed.

    start() itself never assigns ``_init_task`` or resets shutdown state directly (design:
    "start() calls the public initialization front door but never assigns _init_task itself").
    Only the coordinated ``initialize()`` call the joiner makes does that, once it actually
    runs — so this test waits for that to happen instead of asserting synchronously.
    """
    resource = await make_initialized_shutdown_counter()

    await resource.shutdown()
    assert resource.shutdown_completed is True

    start(resource)
    # The pre-existing `_init_task` reference from make_initialized_shutdown_counter() is
    # already non-None (though done), so waiting on "is not None" alone would pass immediately
    # without ever letting start()'s spawned joiner run. Wait for the actual effect instead.
    await wait_for(lambda: not resource.shutdown_completed, desc="coordinator accepted new init attempt")
    assert resource._init_task is not None, "start() should have led to an init task being assigned"

    # Cleanup: await the spawned init task, then shut down
    assert resource._init_task is not None
    await resource._init_task
    await resource.shutdown()


async def test_shutdown_immediately_after_start_does_not_leave_resource_running():
    """A shutdown() called immediately after start(), with no intervening await, must not be
    overtaken by that pending start.

    Regression test: start()'s joiner does not assign ``_init_task`` synchronously -- only the
    joiner actually running ``coordinate_initialize()`` does that, which can be a full
    event-loop turn later. Without ``_pending_start_task`` tracking that pending joiner,
    ``shutdown()``'s ``_observe_active_initializer()`` would see ``_init_task`` still ``None``,
    conclude there was nothing to cancel, and complete cleanly -- only for the still-pending
    joiner to resume afterward, consume the just-stored safe report, and initialize the
    resource anyway, leaving it running after the explicit shutdown had already returned.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette=hassette)

    start(resource)
    # No await between start() and shutdown(): the joiner has not had an event-loop turn yet.
    report = await resource.shutdown()

    assert report.is_restart_safe is True
    assert resource.status == ResourceStatus.STOPPED, (
        f"resource must stay STOPPED after an explicit shutdown, got {resource.status}"
    )
    assert resource._init_task is None or resource._init_task.done()
    assert resource._pending_start_task is None


async def test_shutdown_after_completed_shutdown_cancels_queued_start():
    """A shutdown() called immediately after start(), on a resource that already completed a
    prior clean shutdown, must not be overtaken by that pending start either.

    Regression test: distinct from ``test_shutdown_immediately_after_start_does_not_leave_
    resource_running`` above, which covers the *first* shutdown attempt (``_shutdown_task`` is
    still ``None`` at that point, so ``coordinate_shutdown()`` creates a fresh coordinator that
    calls ``_observe_active_initializer()`` and cancels the pending joiner). Here the resource
    has already shut down once, so ``_shutdown_task`` is a *completed* task -- it stays that way
    until the next accepted ``initialize()`` attempt consumes the report and clears it (see
    ``coordinate_initialize()``). Without the ``elif task.done():`` branch in
    ``coordinate_shutdown()``, this second ``shutdown()`` call would see a non-``None`` task and
    simply return the already-stored report without ever cancelling the newly-queued
    ``_pending_start_task`` -- letting that joiner resume afterward, consume the report, and
    initialize the resource despite the explicit shutdown having already returned.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette=hassette)

    await resource.initialize()
    first_report = await resource.shutdown()
    assert first_report.is_restart_safe is True

    start(resource)
    # No await between start() and shutdown(): the joiner has not had an event-loop turn yet.
    second_report = await resource.shutdown()

    assert second_report.is_restart_safe is True
    assert resource.status == ResourceStatus.STOPPED, (
        f"resource must stay STOPPED after the second explicit shutdown, got {resource.status}"
    )
    assert resource._init_task is None or resource._init_task.done()
    assert resource._pending_start_task is None


async def test_ordered_children_for_shutdown_returns_reversed():
    """ordered_children_for_shutdown() returns children in reverse insertion order."""
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child_a = parent.add_child(ShutdownCounter)
    child_b = parent.add_child(ShutdownCounter)
    child_c = parent.add_child(ShutdownCounter)

    ordered = ordered_children_for_shutdown(parent)
    assert ordered == [child_c, child_b, child_a], f"Expected [C, B, A], got {ordered}"


async def test_shutdown_propagates_to_children_in_reverse_order():
    """Parent with 3 children: shutdown propagates in reverse insertion order."""
    parent, child_a = make_parent_with_child(shutdown_order, OrderTrackingChild)
    child_b = parent.add_child(OrderTrackingChild)
    child_c = parent.add_child(OrderTrackingChild)

    await parent.initialize()
    await child_a.initialize()
    await child_b.initialize()
    await child_c.initialize()

    await parent.shutdown()

    # Children should be shut down in reverse insertion order: C, B, A
    assert shutdown_order == [
        child_c.unique_name,
        child_b.unique_name,
        child_a.unique_name,
    ], f"Expected reverse order, got {shutdown_order}"


async def test_shutdown_propagation_error_tolerance():
    """Middle child raises during shutdown; other children still shut down."""
    parent, child_a = make_parent_with_child(shutdown_order, OrderTrackingChild)
    child_b = parent.add_child(ErrorChild)  # will raise
    child_c = parent.add_child(OrderTrackingChild)

    await parent.initialize()
    await child_a.initialize()
    await child_b.initialize()
    await child_c.initialize()

    await parent.shutdown()

    # All three children should have had on_shutdown called (ErrorChild appends before raising)
    assert child_c.unique_name in shutdown_order
    assert child_b.unique_name in shutdown_order
    assert child_a.unique_name in shutdown_order
    assert len(shutdown_order) == 3


async def make_parent_with_exploding_child(
    message: str, stored_report: ShutdownOutcome | None = None
) -> tuple[SimpleParent, ShutdownCounter, ShutdownCounter]:
    """Build an initialized parent with two ``ShutdownCounter`` children, ``(parent, child_ok, child_broken)``.

    ``child_broken.shutdown`` is replaced with a coroutine that raises ``RuntimeError(message)``.
    When ``stored_report`` is given, it is written to the child's ``_shutdown_outcome`` before
    raising -- mirroring how ``_run_shutdown_coordinator()``'s ``except Exception`` branch stores
    an outcome on the child before re-raising.
    """
    parent = SimpleParent(make_mock_hassette(sealed=False))
    child_ok = parent.add_child(ShutdownCounter)
    child_broken = parent.add_child(ShutdownCounter)
    for resource in (parent, child_ok, child_broken):
        await resource.initialize()

    async def exploding_shutdown():
        if stored_report is not None:
            child_broken._shutdown_outcome = stored_report
        raise RuntimeError(message)

    # Bypass the @final descriptor by setting on the instance dict.
    object.__setattr__(child_broken, "shutdown", exploding_shutdown)
    return parent, child_ok, child_broken


async def test_shutdown_propagation_completes_despite_child_exception():
    """Parent completes shutdown even when a child's shutdown() raises unexpectedly.

    This tests the gather(return_exceptions=True) safety net: even if shutdown()
    itself raises (not just on_shutdown hooks), the parent still sets
    shutdown_completed and processes remaining children.
    """
    parent, child_ok, _ = await make_parent_with_exploding_child("unexpected boom")

    await parent.shutdown()

    # Parent must still complete shutdown
    assert parent.shutdown_completed is True
    # The working child should have been shut down (it's in reverse order, so child_ok runs second)
    assert child_ok.shutdown_count == 1


async def test_shutdown_propagation_skips_completed_children():
    """Pre-shutting down a child means parent propagation is a no-op for that child."""
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await child.initialize()

    # Pre-shutdown the child directly
    await child.shutdown()
    assert child.shutdown_count == 1

    # Now shutdown the parent — propagation calls child.shutdown() again,
    # but shutdown_completed makes it a no-op
    await parent.shutdown()
    assert child.shutdown_count == 1, f"Expected 1, got {child.shutdown_count}"


async def test_shutdown_propagation_with_no_children():
    """Leaf Resource (no children) shuts down normally without errors."""
    hassette = make_mock_hassette(sealed=False)
    leaf = ShutdownCounter(hassette)

    await leaf.initialize()
    await leaf.shutdown()

    assert leaf.shutdown_count == 1
    assert leaf.shutdown_completed is True


async def test_hanging_child_hook_times_out_and_parent_completes():
    """A child whose hook hangs is cut off at its own bound; the parent and its other children still finish."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    parent = SimpleParent(hassette)
    hanging = parent.add_child(HangingChild)
    normal = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await hanging.initialize()
    await normal.initialize()

    await parent.shutdown()

    assert parent.shutdown_completed is True
    assert hanging.shutdown_completed is True
    assert hanging.shutting_down is False
    hanging_report = hanging.shutdown_outcome
    assert hanging_report is not None
    assert hanging_report.result is ShutdownResult.TIMED_OUT
    assert normal.shutdown_completed is True


async def test_hanging_hook_is_cut_off_by_its_own_bound_and_recorded_as_timed_out():
    """A hook that outlives ``shutdown_timeout_seconds`` is cancelled and recorded as timed out, not
    raised, and the body carries on through its later stages without being force-terminated.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    resource = HangingChild(hassette)
    await resource.initialize()

    report = await resource.shutdown()

    assert report.result is ShutdownResult.TIMED_OUT
    assert resource.status == ResourceStatus.STOPPED


class StubbornInitializer(Resource):
    """Resource whose ``on_initialize()`` ignores every cancellation until ``release`` is set."""

    entered: asyncio.Event
    release: asyncio.Event

    async def on_initialize(self) -> None:
        self.entered.set()
        while not self.release.is_set():
            with contextlib.suppress(asyncio.CancelledError):
                await self.release.wait()


async def test_a_pending_initializer_is_named_by_its_task_name():
    """An initializer still running after its bounded wait is named in ``still_running`` by its task name,
    so the outcome is restart-unsafe and the needs-restart record names it.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
    resource = StubbornInitializer(hassette)
    resource.entered = asyncio.Event()
    resource.release = asyncio.Event()
    start(resource)
    await asyncio.wait_for(resource.entered.wait(), timeout=1)

    try:
        outcome = await resource.shutdown()
    finally:
        resource.release.set()

    assert outcome.still_running == (f"resource:initialize:{resource.unique_name}",)
    assert outcome.is_restart_safe is False


class CancelSwallowingChild(Resource):
    """Resource whose ``on_shutdown()`` catches its cancellation and returns normally."""

    async def on_shutdown(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(1000)


async def test_hook_that_swallows_its_cancellation_and_returns_is_recorded_as_timed_out():
    """A hook cut off by its bound times out even when it catches the cancellation and returns."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    resource = CancelSwallowingChild(hassette)
    await resource.initialize()

    report = await resource.shutdown()

    assert report.result is ShutdownResult.TIMED_OUT


class TimeoutRaisingChild(Resource):
    """Resource whose ``on_shutdown()`` raises ``TimeoutError`` itself, well inside its bound."""

    async def on_shutdown(self) -> None:
        raise TimeoutError("the hook's own operation timed out")


async def test_hook_raising_timeout_error_is_recorded_as_failed_not_timed_out():
    """A hook that raises ``TimeoutError`` on its own raised; only a hook its bound cut off timed out."""
    hassette = make_mock_hassette(sealed=False)
    resource = TimeoutRaisingChild(hassette)
    await resource.initialize()

    report = await resource.shutdown()

    assert report.result is ShutdownResult.FAILED


async def test_hook_bound_is_clamped_to_the_shutdown_deadline():
    """A hanging hook gets ``shutdown_timeout_seconds`` shortened to what is left of the deadline."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = 30.0

    resource = HangingChild(hassette)
    await resource.initialize()
    resource._shutdown_deadline = deadline_in(0.2)

    loop = asyncio.get_running_loop()
    start_time = loop.time()
    report = await asyncio.wait_for(resource.shutdown(), timeout=10)
    elapsed = loop.time() - start_time

    assert elapsed < 3.0, f"the hook ran past the 0.2s deadline toward its 30s cap ({elapsed:.2f}s)"
    assert report.result is ShutdownResult.TIMED_OUT


async def test_accepted_initialization_clears_the_previous_shutdown_deadline():
    """A deadline belongs to one shutdown attempt; re-initializing after a clean stop clears it."""
    resource = await make_initialized_shutdown_counter()
    resource._shutdown_deadline = deadline_in(5.0)

    report = await resource.shutdown()
    assert report.is_restart_safe is True

    await resource.initialize()

    assert resource._shutdown_deadline is None


async def test_cancelling_one_shutdown_awaiter_does_not_cancel_shared_attempt():
    """Cancelling one caller's own wrapping task around ``shutdown()`` must not cancel the
    shared ``_shutdown_task`` attempt -- the other concurrent caller still receives a normal
    completed report and the shared task/body are left running to completion.

    ``coordinate_shutdown()`` shields the shared task from each individual awaiter
    (``await asyncio.shield(task)``); cancelling one caller's outer wrapping task only
    interrupts that caller's own await, not the shielded shared task underneath it.
    """
    resource = await make_initialized_shutdown_counter()

    calls: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _gated_on_shutdown() -> None:
        calls.append("called")
        entered.set()
        await release.wait()
        resource.shutdown_count += 1

    resource.on_shutdown = _gated_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

    first = asyncio.create_task(resource.shutdown())
    await asyncio.wait_for(entered.wait(), timeout=1)

    second = asyncio.create_task(resource.shutdown())

    # Cancel only the first caller's own wrapping task.
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    shared_task = resource._shutdown_task
    assert shared_task is not None
    assert not shared_task.done(), "cancelling one awaiter must not cancel the shared attempt"

    # Release the gate; the shared attempt completes normally and the surviving caller gets
    # a real completed report, not a CancelledError.
    release.set()
    report = await second

    assert shared_task.done()
    assert not shared_task.cancelled()
    assert report is resource._shutdown_outcome
    assert report.is_restart_safe is True
    assert calls == ["called"], "on_shutdown must have run exactly once despite the cancelled awaiter"


async def test_shutdown_rejects_reentrant_call_from_shutdown_hook():
    """A shutdown hook that calls ``self.shutdown()`` (or another lifecycle front door) on
    itself must be rejected with ``LifecycleReentryError`` before any duplicate task creation
    or state mutation -- the calling task *is* the shutdown coordinator being awaited.
    """
    resource = await make_initialized_shutdown_counter()

    captured: list[BaseException] = []
    calls: list[str] = []

    async def _reentrant_on_shutdown() -> None:
        calls.append("called")
        resource.shutdown_count += 1
        try:
            await resource.shutdown()
        except LifecycleReentryError as exc:
            captured.append(exc)

    resource.on_shutdown = _reentrant_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

    report = await resource.shutdown()

    assert len(captured) == 1
    assert isinstance(captured[0], LifecycleReentryError)
    assert calls == ["called"], "the re-entrant call must not have re-run shutdown"
    assert resource.shutdown_count == 1
    assert report is resource._shutdown_outcome


class TrulyResistantChild(Resource):
    """Resource whose ``on_shutdown()`` catches its own cancellation and re-blocks forever.

    Distinct from ``HangingChild``: a plain ``Event().wait()`` is cut off by its hook bound and
    resolves inside the shutdown body. Swallowing the injected ``CancelledError`` and re-awaiting
    resists that bound too (the timeout context manager only injects cancellation once), so only the
    operation's owner walking away -- ``_force_terminal()`` -- can end its shutdown.
    """

    swallowed: asyncio.Event

    async def on_initialize(self) -> None:
        self.swallowed = asyncio.Event()

    async def on_shutdown(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:  # noqa: ASYNC103 -- deliberately swallowed, this is the point of the test
            self.swallowed.set()
            await asyncio.Event().wait()  # ignore cancellation and hang forever


async def test_resistant_hook_holds_shutdown_until_the_owner_force_terminates():
    """Nothing inside the shutdown walks away from a hook that swallows its cancellation: the attempt
    waits until the owner force-terminates the resource, then every caller gets the forced report and
    the body is cancelled rather than left running unobserved.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    resource = TrulyResistantChild(hassette)
    await resource.initialize()

    shutdown = asyncio.create_task(resource.shutdown())
    await asyncio.wait_for(resource.swallowed.wait(), timeout=5)
    assert not shutdown.done(), "an interior node must not walk away from a body that outlives its hooks' bound"

    resource._force_terminal()
    report = await asyncio.wait_for(shutdown, timeout=5)

    assert report.result is ShutdownResult.INCOMPLETE
    assert report.is_restart_safe is False
    body_task = resource._shutdown_body_task
    assert body_task is not None
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(body_task, timeout=5)
    assert body_task.cancelled()


async def test_shutdown_children_records_child_shutdown_failed_and_continues_siblings():
    """A child whose ``shutdown()`` call itself raises (not just a hook inside it) makes the parent's
    outcome ``INCOMPLETE`` with a reason naming the child, and siblings still complete via
    ``asyncio.gather(return_exceptions=True)``.
    """
    parent, child_ok, child_broken = await make_parent_with_exploding_child("unexpected boom")

    report = await parent.shutdown()

    assert report.is_restart_safe is False
    assert report.result is ShutdownResult.INCOMPLETE
    assert report.reason == f"{child_broken.unique_name}'s shutdown raised RuntimeError"
    assert child_ok.shutdown_count == 1, "sibling must still complete despite the broken child"


async def test_shutdown_children_merges_child_report_when_shutdown_raises():
    """When a child's ``shutdown()`` call raises from *outside* its own ``_shutdown_body()`` --
    e.g. the coordinator itself failing (see ``_run_shutdown_coordinator()``'s ``except Exception``
    branch in ``lifecycle.py``, which stores an outcome on the child before re-raising) -- the parent
    merges that stored outcome first, so its reason naming the step wins over the generic "shutdown raised".
    """
    stored = incomplete("child's shutdown coordinator raised RuntimeError")
    parent, child_ok, _child_broken = await make_parent_with_exploding_child("coordinator boom", stored_report=stored)

    report = await parent.shutdown()

    assert report.is_restart_safe is False
    assert report.result is ShutdownResult.INCOMPLETE
    assert report.reason == stored.reason, "the child's stored reason must win over the generic one"
    assert child_ok.shutdown_count == 1, "sibling must still complete despite the broken child"


async def test_task_bucket_shutdown_stage_seals_before_cleanup_and_records_pending_tasks():
    """The TaskBucket shutdown stage seals the bucket and records ``TASKS_PENDING`` with the
    straggling task's name -- before ``cleanup()`` runs, so a task spawned before shutdown but
    still pending after the bounded cancellation wait is rejected as new work and reported by
    name.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.task_cancellation_timeout_seconds = 0.05
    resource = ConcreteResource(hassette=hassette)
    await resource.initialize()

    entered = asyncio.Event()
    never_set = asyncio.Event()

    async def _resist_cancellation() -> None:
        entered.set()
        with contextlib.suppress(asyncio.CancelledError):
            await never_set.wait()
        await never_set.wait()  # keep the task genuinely pending past the bounded wait

    # A plain `make_mock_hassette()` resource never installs the loop's custom TaskBucket task
    # factory (only `HassetteHarness`/real `Hassette.run()` do) -- `task_bucket.spawn()`'s fast
    # path relies on that factory to auto-register the task, so it would silently create an
    # untracked task here. Create the task directly and register it via `add()` instead, which
    # tracks it regardless of the installed task factory.
    task = asyncio.create_task(_resist_cancellation(), name="straggler")
    resource.task_bucket.add(task)
    # Let the task actually start and reach its first await before shutdown() cancels it --
    # cancelling a task that has never run its first step delivers CancelledError before the
    # coroutine body (including the `suppress` block) ever executes, so it would not resist
    # cancellation at all.
    await asyncio.wait_for(entered.wait(), timeout=1)

    cleanup_saw_sealed = []
    original_cleanup = resource.cleanup

    async def _spying_cleanup() -> None:
        cleanup_saw_sealed.append(resource.task_bucket.is_sealed)
        await original_cleanup()

    resource.cleanup = _spying_cleanup  # pyright: ignore[reportAttributeAccessIssue]

    try:
        report = await resource.shutdown()

        assert cleanup_saw_sealed == [True], "TaskBucket must already be sealed by the time cleanup() runs"
        assert "straggler" in report.still_running
        assert report.is_restart_safe is False
    finally:
        # The straggler task ignores its first cancellation by design (that is what makes it a
        # straggler) -- clean it up unconditionally so it can never outlive this test, whether
        # the assertions above pass or fail.
        never_set.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class SlowCleanupParent(SimpleParent):
    """Parent whose ``cleanup()`` would run past its fixed ``CLEANUP_SECONDS`` cap."""

    async def cleanup(self) -> None:
        await asyncio.sleep(5)


async def test_slow_cleanup_is_cut_at_its_cap_and_children_still_shut_down():
    """``cleanup()`` gets ``CLEANUP_SECONDS``; one that runs longer is cut off, and the children's
    shutdown and the STOPPED event still follow.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    parent = SlowCleanupParent(hassette)
    hanging = parent.add_child(HangingChild)
    await parent.initialize()
    await hanging.initialize()

    loop = asyncio.get_running_loop()
    start_time = loop.time()
    report = await asyncio.wait_for(parent._run_post_hook_shutdown_stage(), timeout=10)
    elapsed = loop.time() - start_time

    assert report.result is ShutdownResult.TIMED_OUT
    assert report.result is ShutdownResult.TIMED_OUT, "the hanging child's hook timeout is merged in"
    assert elapsed < 3.0, f"cleanup ran past its cap ({elapsed:.2f}s)"
    assert hanging.shutdown_completed is True

    stopped_events = [
        call.args[0]
        for call in hassette.send_event.call_args_list
        if getattr(call.args[0].payload.data, "status", None) == ResourceStatus.STOPPED
    ]
    assert stopped_events, "the STOPPED event must still be emitted after a slow cleanup()"


class SlowBodyResource(Resource):
    """Resource whose shutdown body itself (not a hook) takes longer than ``shutdown_timeout_seconds``."""

    async def _shutdown_body(self) -> ShutdownOutcome:
        await asyncio.sleep(0.3)
        return await super()._shutdown_body()


async def test_coordinator_waits_for_the_body_without_a_bound_of_its_own():
    """Only leaves bound themselves: a body that outlasts ``shutdown_timeout_seconds`` without any hook
    hanging is waited for and completes restart-safe.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    resource = SlowBodyResource(hassette)
    await resource.initialize()

    report = await resource.shutdown()

    assert report.is_restart_safe is True, f"expected a clean outcome, got {report}"


def raise_boom(_resource, _reason=None):
    raise RuntimeError("boom")


async def test_coordinator_failure_records_coordinator_failed_and_blocks_restart(monkeypatch):
    """When something raises inside the coordinator's try body itself (not the shutdown body
    task), the outer ``except Exception`` block stores a ``COORDINATOR_FAILED`` report, the
    exception propagates out of ``shutdown()``, and a subsequent ``initialize()`` is refused via
    ``RestartRefusedError`` -- the "a completed attempt always produces a report" invariant holds
    even when the coordinator fails outside the shutdown body.
    """
    resource = await make_initialized_shutdown_counter()

    # request_shutdown() is called unqualified inside _run_shutdown_coordinator's try body, so
    # patching the module-level name it resolves against is enough to fail the coordinator
    # before it ever creates the shutdown body task.
    monkeypatch.setattr(lifecycle, "request_shutdown", raise_boom)

    with pytest.raises(RuntimeError, match="boom"):
        await resource.shutdown()

    report = resource._shutdown_outcome
    assert report is not None
    assert report.result is ShutdownResult.INCOMPLETE
    assert report.is_restart_safe is False

    with pytest.raises(RestartRefusedError):
        await resource.initialize()


async def test_coordinator_failure_merges_with_preexisting_force_terminal_evidence(monkeypatch):
    """A coordinator failure that occurs after ``FORCED_TERMINAL`` evidence was already stored
    on the resource must merge into that existing report rather than overwrite it -- the
    ``COORDINATOR_FAILED`` cause is added alongside ``FORCED_TERMINAL``, not in place of it.
    """
    resource = await make_initialized_shutdown_counter()

    # Simulate force-terminal evidence already having been recorded on this resource before the
    # coordinator's try body raises (e.g. a concurrent _force_terminal() call from a parent's
    # own shutdown body).
    resource._force_terminal()
    existing_report = resource._shutdown_outcome
    assert existing_report is not None
    assert existing_report.result is ShutdownResult.INCOMPLETE

    monkeypatch.setattr(lifecycle, "request_shutdown", raise_boom)

    with pytest.raises(RuntimeError, match="boom"):
        await resource.shutdown()

    report = resource._shutdown_outcome
    assert report is not None
    assert report.result is ShutdownResult.INCOMPLETE, "pre-existing evidence must not be dropped by the merge"
    assert report.result is ShutdownResult.INCOMPLETE
    assert report.is_restart_safe is False


async def test_service_inherits_shutdown_propagation():
    """Service subclass with children propagates shutdown after serve task cancellation."""
    shutdown_order.clear()
    hassette = make_mock_hassette(sealed=False)
    parent_svc = SimpleService(hassette)

    child_a = parent_svc.add_child(OrderTrackingChild)
    child_b = parent_svc.add_child(OrderTrackingChild)

    await parent_svc.initialize()
    await child_a.initialize()
    await child_b.initialize()

    await wait_for_running(parent_svc)

    await parent_svc.shutdown()

    # Children shut down in reverse order: B, A
    assert shutdown_order == [
        child_b.unique_name,
        child_a.unique_name,
    ], f"Expected reverse order, got {shutdown_order}"


async def test_shutdown_children_survives_root_bucket_sealed_as_global_factory_bucket():
    """Child-shutdown propagation must succeed even when the parent's own TaskBucket is also
    installed as the event loop's global task-factory fallback bucket -- the exact arrangement
    ``Hassette.run_forever()`` uses for the root resource (``loop.set_task_factory(
    make_task_factory(self.task_bucket))``).

    Regression test: ``_run_task_bucket_shutdown_stage()`` seals the parent's own bucket before
    ``_shutdown_children()`` runs. ``asyncio.gather()``'s own implicit task creation for each
    ``child.shutdown()`` coroutine used to route through the loop's task factory with no bucket
    context set, which fell back to the now-sealed global bucket and rejected every
    child-shutdown task immediately -- silently aborting child teardown and surfacing as
    ``SHUTDOWN_BODY_FAILED`` (confirmed via CI: this exact mechanism broke every `system` job).
    """
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)
    child = parent.add_child(ShutdownCounter)

    with sealed_fallback_task_factory(parent.task_bucket):
        await parent.initialize()
        report = await parent.shutdown()

    assert report.is_restart_safe is True, f"expected a clean outcome, got {report}"
    assert child.shutdown_count == 1, "child's on_shutdown must have actually run"
    assert child.status == ResourceStatus.STOPPED


class ThreeHangingHooksParent(Resource):
    """Resource whose ``before_shutdown``, ``on_shutdown`` and ``after_shutdown`` all hang."""

    async def before_shutdown(self) -> None:
        await asyncio.Event().wait()

    async def on_shutdown(self) -> None:
        await asyncio.Event().wait()

    async def after_shutdown(self) -> None:
        await asyncio.Event().wait()


async def test_each_hanging_hook_gets_its_own_bound_and_the_tail_still_runs():
    """Every hook is bounded on its own, so three hanging hooks cost three bounds, not the whole
    shutdown; task-cancel, cleanup and children still run, and nothing is force-terminated.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    parent = ThreeHangingHooksParent(hassette)
    hanging_child = parent.add_child(HangingChild)
    await parent.initialize()
    await hanging_child.initialize()

    loop = asyncio.get_running_loop()
    start = loop.time()
    report = await asyncio.wait_for(parent.shutdown(), timeout=10)
    elapsed = loop.time() - start

    assert report.result is ShutdownResult.TIMED_OUT
    child_report = hanging_child.shutdown_outcome
    assert child_report is not None
    assert child_report.result is ShutdownResult.TIMED_OUT
    assert elapsed < 3.0, f"four 0.1s hook bounds took {elapsed:.2f}s"


async def test_hooks_share_the_deadline_once_it_is_closer_than_their_bounds():
    """Once the shutdown deadline is closer than ``shutdown_timeout_seconds``, every later hook gets only
    what is left of it, so the whole shutdown ends near the deadline.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = 30.0

    parent = ThreeHangingHooksParent(hassette)
    await parent.initialize()
    parent._shutdown_deadline = deadline_in(0.3)

    loop = asyncio.get_running_loop()
    start = loop.time()
    report = await asyncio.wait_for(parent.shutdown(), timeout=10)
    elapsed = loop.time() - start

    assert report.result is ShutdownResult.TIMED_OUT
    assert elapsed < 3.0, f"hooks ran past the 0.3s deadline ({elapsed:.2f}s)"
