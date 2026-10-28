"""Tests for how a child's teardown report decides whether its parent's aggregated report is restart-safe."""

from hassette.resources.teardown import TeardownCause
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ErrorChild, PendingTaskChild, SimpleParent


async def test_shutdown_children_records_child_restart_unsafe_without_raising():
    """A child whose own ``shutdown()`` returns a restart-unsafe report (work still pending) without
    raising makes the parent's aggregated report restart-unsafe too, merging the child's own evidence
    and recording ``CHILD_RESTART_UNSAFE`` with the child's identity.
    """
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)
    child = parent.add_child(PendingTaskChild)

    await parent.initialize()
    await child.initialize()

    report = await parent.shutdown()

    child_report = child.teardown_report
    assert child_report is not None
    assert child_report.is_restart_safe is False

    assert report.is_restart_safe is False
    assert TeardownCause.CHILD_RESTART_UNSAFE in report.causes
    assert "stuck-task" in report.pending_tasks, "child's own evidence must be merged into the parent"
    assert child.unique_name in report.affected_resources


async def test_shutdown_children_keeps_a_child_hook_failure_diagnostic():
    """A child whose ``on_shutdown()`` raised but finished leaves nothing running: its report carries
    ``SHUTDOWN_HOOK_FAILED`` as a diagnostic, and neither it nor the parent's report is restart-unsafe.
    """
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)
    child = parent.add_child(ErrorChild)

    await parent.initialize()
    await child.initialize()

    report = await parent.shutdown()

    assert TeardownCause.SHUTDOWN_HOOK_FAILED in report.causes, "child's own cause must be merged into the parent"
    assert TeardownCause.CHILD_RESTART_UNSAFE not in report.causes
    assert report.is_restart_safe is True
