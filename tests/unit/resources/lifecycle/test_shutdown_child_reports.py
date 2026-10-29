"""Tests for how a child's shutdown outcome decides whether its parent's merged outcome is restart-safe."""

from hassette.resources.shutdown_outcome import ShutdownResult

from .conftest import ErrorChild, PendingTaskChild, SimpleParent, shut_down_parent_with_child


async def test_shutdown_children_records_child_restart_unsafe_without_raising():
    """A child whose own ``shutdown()`` returns a restart-unsafe outcome (work still pending) without
    raising makes the parent's merged outcome restart-unsafe too, through the merge alone: the child's
    still-running names carry over, and the parent adds no evidence of its own.
    """
    _parent, child, report = await shut_down_parent_with_child(SimpleParent, PendingTaskChild)

    child_report = child.shutdown_outcome
    assert child_report is not None
    assert child_report.is_restart_safe is False

    assert report.is_restart_safe is False
    assert report.result is ShutdownResult.DONE
    assert "stuck-task" in report.still_running, "child's own evidence must be merged into the parent"


async def test_shutdown_children_keeps_a_child_hook_failure_diagnostic():
    """A child whose ``on_shutdown()`` raised but finished leaves nothing running: its outcome is
    ``FAILED``, and neither it nor the parent's outcome is restart-unsafe.
    """
    _parent, _child, report = await shut_down_parent_with_child(SimpleParent, ErrorChild)

    assert report.result is ShutdownResult.FAILED, "child's own result must be merged into the parent"
    assert report.is_restart_safe is True
