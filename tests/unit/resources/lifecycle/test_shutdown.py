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

from hassette.exceptions import LifecycleReentryError, RestartRefusedError
from hassette.resources import lifecycle
from hassette.resources.base import Resource
from hassette.resources.lifecycle import compute_shutdown_budget, start
from hassette.resources.operations import ordered_children_for_shutdown
from hassette.resources.teardown import TeardownCause, TeardownReport
from hassette.task_bucket import make_task_factory
from hassette.testing import wait_for
from hassette.types.enums import ResourceStatus
from tests.support.helpers import SHORT_SHUTDOWN_TIMEOUT_SECONDS
from tests.support.mock_hassette import make_mock_hassette
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
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

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


async def test_resource_own_hanging_hook_wins_race_against_coordinator_timeout():
    """A resource's own hanging hook must resolve via ``run_hooks()``'s
    ``asyncio.timeout(hooks_pool_remaining(...))`` bound — recording ``SHUTDOWN_HOOK_FAILED``
    and letting ``_shutdown_body()`` proceed through its later stages — rather than losing the
    race to the coordinator's own outer ``asyncio.wait([body_task], timeout=timeout)`` bound.

    The up-front budget's ``COORDINATOR_MARGIN_FRACTION`` guarantees that the body's stages
    (hooks pool + mandatory tail) finish before the coordinator's outer wait, so the hook's
    inner timeout always fires first by construction.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    resource = HangingChild(hassette)
    await resource.initialize()

    report = await resource.shutdown()

    assert TeardownCause.SHUTDOWN_HOOK_FAILED in report.causes
    assert TeardownCause.SHUTDOWN_BODY_TIMED_OUT not in report.causes, (
        "the hook's own inner timeout must resolve before the coordinator's outer bound fires"
    )
    assert TeardownCause.FORCED_TERMINAL not in report.causes


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


class TrulyResistantChild(Resource):
    """Resource whose ``on_shutdown()`` catches its own cancellation and re-blocks forever.

    Distinct from ``HangingChild``: a plain ``Event().wait()`` with no ``except CancelledError``
    is caught by ``run_hooks()``'s own ``asyncio.timeout(hooks_pool_remaining(...))`` bound
    (``bound_to_shutdown_budget=True`` in ``base.py``'s ``_shutdown_body()``) and resolves with
    a ``TimeoutError`` inside the shutdown body itself -- it no longer needs the outer coordinator
    to force-cancel it. Swallowing the injected ``CancelledError`` and re-awaiting a fresh
    ``Event().wait()`` genuinely resists that inner bound too (the timeout context manager only
    injects cancellation once), so this is what still exercises the coordinator's own external
    force-cancel fallback this test targets.
    """

    async def on_shutdown(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:  # noqa: ASYNC103 -- deliberately swallowed, this is the point of the test
            await asyncio.Event().wait()  # ignore cancellation and hang forever


async def test_resistant_shutdown_body_is_cancelled_after_coordinator_times_out():
    """A shutdown body that outlives the coordinator's bounded observation window is cancelled
    by the coordinator itself in the timeout branch -- it is not left running as an orphaned,
    unobserved task once every external joiner (the ``shutdown()`` caller) has returned.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    resource = TrulyResistantChild(hassette)
    await resource.initialize()

    report = await resource.shutdown()

    # The coordinator's timeout branch calls body_task.cancel() itself before returning --
    # the body (blocked forever on TrulyResistantChild.on_shutdown()'s re-blocking Event().wait())
    # does not outlive the coordinator as an orphaned task.
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


async def test_shutdown_children_merges_child_report_when_shutdown_raises():
    """When a child's ``shutdown()`` call raises from *outside* its own ``_shutdown_body()`` --
    e.g. the coordinator itself failing (``COORDINATOR_FAILED``, see
    ``_run_shutdown_coordinator()``'s ``except Exception`` branch in ``lifecycle.py``, which
    stores evidence on the child's own report before re-raising) -- the parent must merge that
    already-stored report into its own aggregated report, not just record the generic
    ``CHILD_SHUTDOWN_FAILED`` cause and drop the child's concrete cause and ``failed_operations``.
    """
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child_ok = parent.add_child(ShutdownCounter)
    child_broken = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await child_ok.initialize()
    await child_broken.initialize()

    async def exploding_shutdown_with_stored_evidence():
        # Mirrors what _run_shutdown_coordinator()'s except Exception branch does in the real
        # flow: store evidence on the child's own report before re-raising.
        child_broken._teardown_report = TeardownReport(
            causes=(TeardownCause.COORDINATOR_FAILED,), failed_operations=("_run_shutdown_coordinator",)
        )
        raise RuntimeError("coordinator boom")

    # Bypass the @final descriptor by setting on the instance dict.
    object.__setattr__(child_broken, "shutdown", exploding_shutdown_with_stored_evidence)

    report = await parent.shutdown()

    assert report.is_restart_safe is False
    assert TeardownCause.CHILD_SHUTDOWN_FAILED in report.causes
    assert TeardownCause.COORDINATOR_FAILED in report.causes, "child's own stored cause must be merged into the parent"
    assert "_run_shutdown_coordinator" in report.failed_operations
    assert child_broken.unique_name in report.affected_resources
    assert child_ok.shutdown_count == 1, "sibling must still complete despite the broken child"


async def test_shutdown_children_timeout_preserves_finished_safe_child_report():
    """A wave that times out force-terminates only the children still unfinished at that
    point -- a child that already completed cleanly keeps its own restart-safe report unchanged,
    while the unfinished (hanging) child is force-terminated and the parent is
    restart-unsafe overall.

    Uses ``TrulyResistantChild``, not ``HangingChild``: with ``bound_to_shutdown_budget=True``
    on ``run_hooks()``, ``HangingChild.on_shutdown()`` now resolves on its own (as
    ``SHUTDOWN_HOOK_FAILED``) well within ``resource_shutdown_timeout_seconds``.
    ``TrulyResistantChild`` never lets its shutdown hook resolve on its own, so only an
    external force-terminate call can stop it.

    The child's own coordinator now self-resolves at ``resource_shutdown_timeout_seconds *
    (1 - COORDINATOR_MARGIN_FRACTION)`` (its own ``body_deadline``, honored by the
    coordinator's outer wait) -- reliably *before* an ancestor whose wave-level timeout used
    that same full duration, which would make the child's own internal timeout win the race
    every time instead of the parent's. The parent below is therefore given its own explicit,
    much tighter budget so its wave-level timeout is what force-terminates the still-hanging
    child, which is what this test targets.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    parent = SimpleParent(hassette)
    hanging = parent.add_child(TrulyResistantChild)
    normal = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await hanging.initialize()
    await normal.initialize()

    # Call _shutdown_children() directly rather than the full shutdown() coordinator, with an
    # explicit budget much tighter than the child's own resource_shutdown_timeout_seconds --
    # see the docstring above for why this must now be deliberately shorter than the child's
    # own margin-adjusted self-resolution time, not merely different from it.
    parent._shutdown_budget = compute_shutdown_budget(0.05, asyncio.get_running_loop().time())
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


class SlowCleanupParent(SimpleParent):
    """Parent whose ``cleanup()`` consumes a large, real fraction of the shared shutdown
    deadline before completing on its own (not by hitting any timeout).
    """

    async def cleanup(self, timeout: float | None = None) -> None:
        await asyncio.sleep(0.6)


async def test_shutdown_children_uses_remaining_budget_after_slow_cleanup():
    """Regression: children must be bounded by the body deadline even when cleanup is slow.

    ``SlowCleanupParent.cleanup()`` takes 0.6s of real wall-clock time. With a 5.0s total
    budget, the up-front allocation gives task-cancel 1.0s, cleanup 0.5s, and children the
    remaining body budget (body_deadline - now). The cleanup's real 0.6s exceeds its 0.5s
    allocation (it times out), so children start with the body_deadline already partly spent.
    The key property: the whole post-hook stage still finishes within the body_deadline, not
    an independent fresh timeout window after cleanup.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 5.0

    parent = SlowCleanupParent(hassette)
    hanging = parent.add_child(HangingChild)
    await parent.initialize()
    await hanging.initialize()

    loop = asyncio.get_running_loop()
    parent._shutdown_budget = compute_shutdown_budget(5.0, loop.time())
    start_time = loop.time()

    report = await asyncio.wait_for(parent._run_post_hook_shutdown_stage(), timeout=10)
    elapsed = loop.time() - start_time

    assert report.is_restart_safe is False, "the hanging child must produce an unsafe report"
    assert elapsed < 5.5, f"the post-hook stage must finish within the body budget — took {elapsed:.2f}s"

    stopped_events = [
        call.args[0]
        for call in hassette.send_event.call_args_list
        if getattr(call.args[0].payload.data, "status", None) == ResourceStatus.STOPPED
    ]
    assert stopped_events, "the STOPPED event must still be emitted after a slow cleanup()"


def test_compute_shutdown_budget_reserves_nonzero_hooks_pool_for_small_timeouts():
    """Regression: a ``resource_shutdown_timeout_seconds`` too small to fit the full tail
    reservation must still leave the hooks pool a nonzero share, scaled down like every other
    stage -- not collapsed to exactly 0. ``LifecycleConfig`` places no lower bound on this
    setting, so a small value (e.g. 2s) is reachable in practice; before this fix, any
    on_shutdown() hook would be cancelled at its very first suspension point regardless of how
    little work it does, because ``asyncio.timeout(0)`` is already expired.
    """
    now = 100.0
    budget = lifecycle.compute_shutdown_budget(2.0, now)

    assert budget.hooks_pool_deadline > now, "the hooks pool must not collapse to 0"


def test_compute_shutdown_budget_honors_configured_task_cancel_ceiling():
    """Regression: the task-cancel stage must use the caller-supplied ceiling (in production,
    ``lifecycle.task_cancellation_timeout_seconds``), not a hardcoded 1.0s -- a task that
    cooperatively finishes within the configured allowance but after the old hardcoded second
    was previously reported as ``TASKS_PENDING`` even though it completed on time.
    """
    now = 100.0
    budget = lifecycle.compute_shutdown_budget(30.0, now, task_cancel_ceiling=5.0)

    assert budget.task_cancel_seconds == 5.0


class _ObserveTimer:
    """Fake ``_observe_active_initializer``: sleeps for ``seconds``, then records the actually
    measured duration in ``actual_elapsed`` -- read after the sleep so callers self-calibrate
    against real scheduling variance instead of assuming the sleep took exactly ``seconds``.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.actual_elapsed = 0.0

    async def __call__(self, _resource: object) -> bool:
        loop = asyncio.get_running_loop()
        before = loop.time()
        await asyncio.sleep(self.seconds)
        self.actual_elapsed = loop.time() - before
        return True


class _WaitCapture:
    """Fake ``asyncio.wait``: records the ``timeout`` it's called with in ``timeout``, then
    reports the task as still pending without actually waiting.

    Patches ``asyncio.wait`` process-wide, not just ``lifecycle.py``'s reference to it, so the
    exercised path must call it exactly once for this capture to be unambiguous:
    ``_ObserveTimer`` above replaces the initializer-observation phase's own inner
    ``asyncio.wait`` call entirely (see ``lifecycle.py:741``) rather than letting it run for
    real, leaving only the coordinator's outer wait (``lifecycle.py:811``) to hit this patch.
    """

    def __init__(self) -> None:
        self.timeout: float | None = None

    async def __call__(self, tasks: object, *, timeout: float | None = None) -> tuple[set, set]:
        self.timeout = timeout
        return set(), set(tasks)  # (done, pending) -- "still pending" drives the coordinator's timeout branch


async def test_shutdown_coordinator_bounds_body_wait_by_remaining_budget(monkeypatch):
    """Regression: the coordinator's outer wait on the shutdown body must be bounded by the
    remaining time to the shared, un-margin-reduced ``total_deadline`` (``now0 + timeout``),
    not a fresh copy of the full configured timeout measured from whenever the outer wait
    itself happens to start -- otherwise a shutdown attempt whose initializer-observation
    phase already spent real time from the same budget gets that spent time PLUS a full
    timeout again, roughly doubling worst-case shutdown time.

    Asserts directly on the ``timeout`` value the coordinator computes and passes to its outer
    ``asyncio.wait(timeout=...)`` bound (via ``_WaitCapture``, which also short-circuits the
    wait itself) rather than on the real end-to-end elapsed time of a live wait. The two correct
    and buggy outcomes differ by exactly ``observe_seconds``, so measuring wall-clock duration end
    to end needs a real timeout on the order of that difference and a margin on the assertion
    tight enough to still distinguish the two -- vulnerable to ordinary event-loop scheduling
    jitter on a shared, contended CI runner. Capturing the computed argument instead needs no
    live wait at all, and ``_ObserveTimer`` self-calibrates the expected value against its own
    actually measured sleep duration rather than assuming it took exactly ``observe_seconds``.

    Uses ``HangingChild`` as the resource: its ``on_shutdown()`` never completes on its own, so
    ``body_task`` is still pending when the mocked wait returns "not done", and the coordinator's
    own ``if not body_task.done(): body_task.cancel()`` branch is what actually ends it (awaited
    to completion in the ``finally`` block below). ``TrulyResistantChild``'s cancellation-resistant
    behavior is irrelevant here: the mocked wait never actually suspends, so ``body_task`` never
    gets a scheduling turn to run any of its own code before that cancel fires -- a plain hang
    that never completes exercises the coordinator's branch identically, with less fixture
    machinery.
    """
    observe_seconds = 0.3
    total_timeout_seconds = 1.0
    # Generous headroom over the scheduling jitter of the one real `asyncio.sleep()` in
    # `_ObserveTimer` (typically sub-millisecond to a few ms even under load), while staying far
    # below `observe_seconds` -- the gap a buggy fresh-timeout value would actually produce --
    # so it cannot mask a real regression.
    wait_timeout_epsilon_seconds = 0.05
    # Safety net only: bounds the cleanup wait below so a coordinator regression that stops
    # cancelling body_task fails this test outright instead of hanging the suite.
    cleanup_wait_timeout_seconds = 2.0

    observe_timer = _ObserveTimer(observe_seconds)
    monkeypatch.setattr(lifecycle, "_observe_active_initializer", observe_timer)

    wait_capture = _WaitCapture()
    monkeypatch.setattr(asyncio, "wait", wait_capture)

    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = total_timeout_seconds

    resource = HangingChild(hassette)
    await resource.initialize()

    report = await resource.shutdown()

    try:
        assert report.is_restart_safe is False
        # Correct behavior passes total_deadline_remaining() -- the shared deadline minus
        # whatever the observe phase actually consumed, clamped to zero the same way production
        # clamps it (lifecycle.py's total_deadline_remaining()). With this test's fixed
        # `observe_seconds`/`total_timeout_seconds` the clamp never actually engages -- it exists
        # so this expectation stays correct (rather than going negative) if scheduling delays ever
        # push the real observe-phase sleep past the total budget. The bug this guards against
        # passes a fresh `total_timeout_seconds` instead, ignoring that consumption entirely; the
        # two differ by `observe_timer.actual_elapsed`, comfortably above the epsilon below.
        expected_wait_timeout = max(0.0, total_timeout_seconds - observe_timer.actual_elapsed)
        assert wait_capture.timeout == pytest.approx(expected_wait_timeout, abs=wait_timeout_epsilon_seconds), (
            "outer body wait must be bounded by the remaining shared deadline, not a fresh "
            f"timeout -- captured {wait_capture.timeout}, expected ~{expected_wait_timeout:.3f}"
        )
    finally:
        # The coordinator's own else-branch above already cancelled body_task once; a plain
        # hang only needs that single cancel to finish, unlike TrulyResistantChild elsewhere in
        # this file, which needs a second one to defeat its own re-blocking.
        body_task = resource._shutdown_body_task
        if body_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(body_task, timeout=cleanup_wait_timeout_seconds)


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

    report = resource._teardown_report
    assert report is not None
    assert TeardownCause.COORDINATOR_FAILED in report.causes
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
    existing_report = resource._teardown_report
    assert existing_report is not None
    assert TeardownCause.FORCED_TERMINAL in existing_report.causes

    monkeypatch.setattr(lifecycle, "request_shutdown", raise_boom)

    with pytest.raises(RuntimeError, match="boom"):
        await resource.shutdown()

    report = resource._teardown_report
    assert report is not None
    assert TeardownCause.FORCED_TERMINAL in report.causes, "pre-existing evidence must not be dropped by the merge"
    assert TeardownCause.COORDINATOR_FAILED in report.causes
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

    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    loop.set_task_factory(make_task_factory(parent.task_bucket))  # pyright: ignore[reportArgumentType]
    try:
        await parent.initialize()
        report = await parent.shutdown()
    finally:
        loop.set_task_factory(previous_factory)

    assert report.is_restart_safe is True, f"expected a clean report, got causes={report.causes}"
    assert child.shutdown_count == 1, "child's on_shutdown must have actually run"
    assert child.status == ResourceStatus.STOPPED


class ThreeHangingHooksParent(Resource):
    """Resource with three hook stages that all hang: ``before_shutdown``,
    ``on_shutdown``, and ``after_shutdown`` each do ``asyncio.Event().wait()``.

    The hooks pool is shared across all three. With the up-front budget
    allocation, the pool is bounded and all three together cannot starve the
    mandatory tail stages (task-cancel, cleanup, children).
    """

    async def before_shutdown(self) -> None:
        await asyncio.Event().wait()

    async def on_shutdown(self) -> None:
        await asyncio.Event().wait()

    async def after_shutdown(self) -> None:
        await asyncio.Event().wait()


async def test_multiple_hanging_hooks_cannot_starve_mandatory_tail():
    """Worst-case budget test: three hooks all hang, verifying the mandatory tail is guaranteed.

    1. All hooks time out (SHUTDOWN_HOOK_FAILED) — the hooks pool is exhausted.
    2. The mandatory tail still runs: task-cancel completes, cleanup completes, and
       children get their guaranteed floor (CHILD_SHUTDOWN_TIMED_OUT, not
       SHUTDOWN_BODY_TIMED_OUT — the body finishes before the coordinator abandons it).
    3. Total elapsed time stays within the coordinator's outer budget.

    This is the test that would have caught the old waterfall compounding bug: with
    fraction-of-remainder budgets, three hooks each taking 0.9 of the shrinking
    remainder leave negligible time for everything after them. With up-front allocation,
    the hooks pool is bounded and the tail reservation is guaranteed.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 5.0

    parent = ThreeHangingHooksParent(hassette)
    hanging_child = parent.add_child(HangingChild)
    await parent.initialize()
    await hanging_child.initialize()

    loop = asyncio.get_running_loop()
    start = loop.time()

    report = await asyncio.wait_for(parent.shutdown(), timeout=10)

    elapsed = loop.time() - start

    assert TeardownCause.SHUTDOWN_HOOK_FAILED in report.causes, (
        "hanging hooks must be caught by the hooks pool deadline"
    )
    assert TeardownCause.SHUTDOWN_BODY_TIMED_OUT not in report.causes, (
        "the body must finish before the coordinator's outer bound — "
        "if SHUTDOWN_BODY_TIMED_OUT appears, the mandatory tail was starved"
    )
    assert TeardownCause.FORCED_TERMINAL not in report.causes, (
        "force-terminal means the coordinator gave up — the body should self-complete"
    )

    child_report = hanging_child.teardown_report
    assert child_report is not None, "hanging child must have a teardown report"
    assert child_report.is_restart_safe is False

    assert elapsed < 5.5, (
        f"total shutdown must stay within the 5.0s coordinator budget (with margin) — took {elapsed:.2f}s"
    )
