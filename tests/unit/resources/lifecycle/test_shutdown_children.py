"""Tests for how a parent's shutdown records child outcomes and uses its budget."""

import asyncio
import contextlib

from hassette_wire import ResourceStatus

from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult, incomplete_outcome
from tests.support.helpers import SHORT_SHUTDOWN_TIMEOUT_SECONDS
from tests.support.mock_hassette import make_mock_hassette
from tests.support.task_buckets import sealed_fallback_task_factory
from tests.unit.resources.conftest import ConcreteResource

from .conftest import (
    HangingChild,
    ShutdownCounter,
    SimpleParent,
)


async def make_parent_with_exploding_child(
    message: str, stored_outcome: ShutdownOutcome | None = None
) -> tuple[SimpleParent, ShutdownCounter, ShutdownCounter]:
    """Build an initialized parent with two ``ShutdownCounter`` children, ``(parent, child_ok, child_broken)``.

    ``child_broken.shutdown`` is replaced with a coroutine that raises ``RuntimeError(message)``.
    When ``stored_outcome`` is given, it is written to the child's ``_shutdown_outcome`` before
    raising -- mirroring how ``_run_shutdown_coordinator()``'s ``except Exception`` branch stores
    an outcome on the child before re-raising.
    """
    parent = SimpleParent(make_mock_hassette(sealed=False))
    child_ok = parent.add_child(ShutdownCounter)
    child_broken = parent.add_child(ShutdownCounter)
    for resource in (parent, child_ok, child_broken):
        await resource.initialize()

    async def exploding_shutdown():
        if stored_outcome is not None:
            child_broken._shutdown_outcome = stored_outcome
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


async def test_shutdown_children_records_child_shutdown_failed_and_continues_siblings():
    """A child whose ``shutdown()`` call itself raises (not just a hook inside it) makes the parent's
    outcome ``INCOMPLETE`` with a reason naming the child, and siblings still complete via
    ``asyncio.gather(return_exceptions=True)``.
    """
    parent, child_ok, child_broken = await make_parent_with_exploding_child("unexpected boom")

    outcome = await parent.shutdown()

    assert outcome.is_restart_safe is False
    assert outcome.result is ShutdownResult.INCOMPLETE
    assert outcome.reason == f"{child_broken.unique_name}'s shutdown raised RuntimeError"
    assert child_ok.shutdown_count == 1, "sibling must still complete despite the broken child"


async def test_shutdown_children_merges_child_outcome_when_shutdown_raises():
    """When a child's ``shutdown()`` call raises from *outside* its own ``_shutdown_body()`` --
    e.g. the coordinator itself failing (see ``_run_shutdown_coordinator()``'s ``except Exception``
    branch in ``lifecycle.py``, which stores an outcome on the child before re-raising) -- the parent
    merges that stored outcome first, so its reason naming the step wins over the generic "shutdown raised".
    """
    stored = incomplete_outcome("child's shutdown coordinator raised RuntimeError")
    parent, child_ok, _child_broken = await make_parent_with_exploding_child("coordinator boom", stored_outcome=stored)

    outcome = await parent.shutdown()

    assert outcome.is_restart_safe is False
    assert outcome.result is ShutdownResult.INCOMPLETE
    assert outcome.reason == stored.reason, "the child's stored reason must win over the generic one"
    assert child_ok.shutdown_count == 1, "sibling must still complete despite the broken child"


async def test_task_bucket_shutdown_stage_seals_before_cleanup_and_records_pending_tasks():
    """The TaskBucket shutdown stage seals the bucket and records the
    straggling task's name in ``still_running`` -- before ``cleanup()`` runs, so a task spawned before shutdown but
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
        outcome = await resource.shutdown()

        assert cleanup_saw_sealed == [True], "TaskBucket must already be sealed by the time cleanup() runs"
        assert "straggler" in outcome.still_running
        assert outcome.is_restart_safe is False
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
    outcome = await asyncio.wait_for(parent._run_post_hook_shutdown_stage(), timeout=10)
    elapsed = loop.time() - start_time

    assert outcome.result is ShutdownResult.TIMED_OUT, "the hanging child's hook timeout is merged in"
    assert elapsed < 3.0, f"cleanup ran past its cap ({elapsed:.2f}s)"
    assert hanging.shutdown_completed is True

    stopped_events = [
        call.args[0]
        for call in hassette.send_event.call_args_list
        if getattr(call.args[0].payload.data, "status", None) == ResourceStatus.STOPPED
    ]
    assert stopped_events, "the STOPPED event must still be emitted after a slow cleanup()"


async def test_a_cleanup_cut_at_its_cap_is_failed_not_timed_out():
    """A ``cleanup()`` cut off at its cap ranks ``FAILED``: an app stop reads ``TIMED_OUT`` as a timed-out
    hook and fails the stop, and a slow ``cleanup()`` alone must leave the stop STOPPED.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
    parent = SlowCleanupParent(hassette)
    await parent.initialize()

    outcome = await asyncio.wait_for(parent._run_post_hook_shutdown_stage(), timeout=10)

    assert outcome.result is ShutdownResult.FAILED
    assert outcome.is_restart_safe is True
    assert outcome.reason is not None
    assert "cleanup() timed out" in outcome.reason


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
    a raised shutdown body (confirmed via CI: this exact mechanism broke every `system` job).
    """
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)
    child = parent.add_child(ShutdownCounter)

    with sealed_fallback_task_factory(parent.task_bucket):
        await parent.initialize()
        outcome = await parent.shutdown()

    assert outcome.is_restart_safe is True, f"expected a clean outcome, got {outcome}"
    assert child.shutdown_count == 1, "child's on_shutdown must have actually run"
    assert child.status == ResourceStatus.STOPPED
