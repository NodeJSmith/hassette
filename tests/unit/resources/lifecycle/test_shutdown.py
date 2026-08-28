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

from hassette.exceptions import LifecycleReentryError
from hassette.resources.lifecycle import start
from hassette.resources.operations import ordered_children_for_shutdown
from hassette.resources.teardown import TeardownCause
from hassette.test_utils import make_mock_hassette, wait_for
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


async def test_shutdown_propagation_completes_despite_child_exception():
    """Parent completes shutdown even when a child's shutdown() raises unexpectedly.

    This tests the gather(return_exceptions=True) safety net: even if shutdown()
    itself raises (not just on_shutdown hooks), the parent still sets
    shutdown_completed and processes remaining children.
    """
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child_ok = parent.add_child(ShutdownCounter)
    child_broken = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await child_ok.initialize()
    await child_broken.initialize()

    # Monkeypatch child_broken.shutdown to raise an unexpected error
    async def exploding_shutdown():
        raise RuntimeError("unexpected boom")

    # Bypass the @final descriptor by setting on the instance dict
    object.__setattr__(child_broken, "shutdown", exploding_shutdown)

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


async def test_shutdown_propagation_timeout_forces_terminal_state():
    """When child shutdown times out, timed-out children are forced to consistent terminal state."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 0.1  # very short timeout

    parent = SimpleParent(hassette)
    hanging = parent.add_child(HangingChild)
    normal = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await hanging.initialize()
    await normal.initialize()

    await parent.shutdown()

    # Parent should complete despite the hanging child
    assert parent.shutdown_completed is True
    # Hanging child should be forced to terminal state
    assert hanging.shutdown_completed is True
    assert hanging.shutting_down is False
    # Normal child should also be shut down (gather runs concurrently)
    assert normal.shutdown_completed is True


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
    assert report is resource._teardown_report
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
    assert report is resource._teardown_report


async def test_resistant_shutdown_body_is_cancelled_after_coordinator_times_out():
    """A shutdown body that outlives the coordinator's bounded observation window is cancelled
    by the coordinator itself in the timeout branch -- it is not left running as an orphaned,
    unobserved task once every external joiner (the ``shutdown()`` caller) has returned.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 0.1  # short bound

    resource = HangingChild(hassette)
    await resource.initialize()

    report = await resource.shutdown()

    # The coordinator's timeout branch calls body_task.cancel() itself before returning --
    # the body (blocked forever on HangingChild.on_shutdown's Event().wait()) does not outlive
    # the coordinator as an orphaned task.
    body_task = resource._shutdown_body_task
    assert body_task is not None
    assert report.is_restart_safe is False  # timed-out/pending body is never restart-safe evidence

    # Let the requested cancellation actually land, then confirm the exception observer already
    # consumed the CancelledError -- i.e. task.cancelled() can be read afterward without raising
    # because the done callback already retrieved it.
    with contextlib.suppress(asyncio.CancelledError):
        await body_task
    assert body_task.cancelled()


async def test_shutdown_children_records_child_restart_unsafe_without_raising():
    """A child whose own ``shutdown()`` call returns a report with ``is_restart_safe`` ``False``
    (without raising -- ``ErrorChild`` fails inside ``on_shutdown()``, which ``run_hooks(...,
    continue_on_error=True)`` catches and turns into a ``SHUTDOWN_HOOK_FAILED`` report rather
    than an exception) makes the parent's aggregated report ``is_restart_safe`` ``False`` too,
    merging the child's own cause and recording ``CHILD_RESTART_UNSAFE`` with the child's identity.
    """
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)
    child = parent.add_child(ErrorChild)

    await parent.initialize()
    await child.initialize()

    report = await parent.shutdown()

    child_report = child.teardown_report
    assert child_report is not None
    assert child_report.is_restart_safe is False
    assert TeardownCause.SHUTDOWN_HOOK_FAILED in child_report.causes

    assert report.is_restart_safe is False
    assert TeardownCause.CHILD_RESTART_UNSAFE in report.causes
    assert TeardownCause.SHUTDOWN_HOOK_FAILED in report.causes, "child's own cause must be merged into the parent"
    assert child.unique_name in report.affected_resources


async def test_shutdown_children_records_child_shutdown_failed_and_continues_siblings():
    """A child whose ``shutdown()`` call itself raises (not just a hook inside it) adds
    ``CHILD_SHUTDOWN_FAILED`` and the child's identity to the parent's aggregated report, and
    siblings still complete via ``asyncio.gather(return_exceptions=True)``.
    """
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child_ok = parent.add_child(ShutdownCounter)
    child_broken = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await child_ok.initialize()
    await child_broken.initialize()

    async def exploding_shutdown():
        raise RuntimeError("unexpected boom")

    # Bypass the @final descriptor by setting on the instance dict.
    object.__setattr__(child_broken, "shutdown", exploding_shutdown)

    report = await parent.shutdown()

    assert report.is_restart_safe is False
    assert TeardownCause.CHILD_SHUTDOWN_FAILED in report.causes
    assert child_broken.unique_name in report.affected_resources
    assert child_ok.shutdown_count == 1, "sibling must still complete despite the broken child"


async def test_shutdown_children_timeout_preserves_finished_safe_child_report():
    """A wave that times out force-terminates only the children still unfinished at that
    point -- a child that already completed cleanly keeps its own restart-safe report unchanged,
    while the unfinished (hanging) child is force-terminated and the parent is
    restart-unsafe overall.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 0.1

    parent = SimpleParent(hassette)
    hanging = parent.add_child(HangingChild)
    normal = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await hanging.initialize()
    await normal.initialize()

    # Call _shutdown_children() directly rather than the full shutdown() coordinator: the
    # coordinator's own whole-body deadline shares the same `resource_shutdown_timeout_seconds`
    # config value, starting its clock earlier (as soon as the body task is created, before
    # hooks/TaskBucket/cleanup even run) -- with an identical duration it would race and usually
    # fire first, producing SHUTDOWN_BODY_TIMED_OUT instead of the child-aggregation evidence
    # this test targets.
    report = await parent._shutdown_children()

    assert report.is_restart_safe is False
    assert TeardownCause.CHILD_SHUTDOWN_TIMED_OUT in report.causes

    hanging_report = hanging.teardown_report
    assert hanging_report is not None
    assert hanging_report.is_restart_safe is False
    assert TeardownCause.FORCED_TERMINAL in hanging_report.causes

    normal_report = normal.teardown_report
    assert normal_report is not None
    assert normal_report.is_restart_safe is True, (
        "a child that already completed cleanly before the wave timed out must keep its restart-safe report"
    )


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

    async def _spying_cleanup(timeout: float | None = None) -> None:
        cleanup_saw_sealed.append(resource.task_bucket.is_sealed)
        await original_cleanup(timeout)

    resource.cleanup = _spying_cleanup  # pyright: ignore[reportAttributeAccessIssue]

    try:
        report = await resource.shutdown()

        assert cleanup_saw_sealed == [True], "TaskBucket must already be sealed by the time cleanup() runs"
        assert TeardownCause.TASKS_PENDING in report.causes
        assert "straggler" in report.pending_tasks
        assert report.is_restart_safe is False
    finally:
        # The straggler task ignores its first cancellation by design (that is what makes it a
        # straggler) -- clean it up unconditionally so it can never outlive this test, whether
        # the assertions above pass or fail.
        never_set.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


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
