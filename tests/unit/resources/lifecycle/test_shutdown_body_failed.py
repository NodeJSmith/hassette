"""Tests for a shutdown body that ends abnormally: its report is restart-unsafe.

The coordinator replaces a raised or cancelled body's evidence with ``SHUTDOWN_BODY_FAILED``, so the
later stages (task cancellation, child shutdown) may never have run and nothing proves the work ended.
"""

import asyncio

from hassette.resources.base import Resource
from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ShutdownCounter, shut_down_parent_with_child


class CancelAwaitingParent(Resource):
    """Parent whose ``on_shutdown`` cancels its own task and awaits it without catching ``CancelledError``."""

    async def on_initialize(self) -> None:
        self.loop_task = self.task_bucket.spawn(asyncio.Event().wait(), name="loop")

    async def on_shutdown(self) -> None:
        self.loop_task.cancel()
        await self.loop_task


async def test_cancelled_error_escaping_a_shutdown_hook_leaves_the_report_restart_unsafe():
    """A ``CancelledError`` from awaiting a task the hook cancelled aborts the body before child shutdown,
    and the report says work may still be running.
    """
    _parent, child, report = await shut_down_parent_with_child(CancelAwaitingParent, ShutdownCounter)

    assert report.result is ShutdownResult.INCOMPLETE
    assert child.shutdown_count == 0, "the aborted body never reached child shutdown"
    assert report.is_restart_safe is False


class RaisingChildrenStageParent(Resource):
    """Parent whose child-shutdown stage raises, so the body ends without a report of its own."""

    async def _shutdown_children(self) -> ShutdownOutcome:
        raise RuntimeError("child stage boom")


async def test_a_shutdown_body_that_raises_leaves_the_report_restart_unsafe():
    """A body that raises an ordinary exception drops its stages' evidence, so the report can't claim the
    attempt's work ended.
    """
    hassette = make_mock_hassette(sealed=False)
    parent = RaisingChildrenStageParent(hassette)
    await parent.initialize()

    report = await parent.shutdown()

    assert report.result is ShutdownResult.INCOMPLETE
    assert report.is_restart_safe is False
