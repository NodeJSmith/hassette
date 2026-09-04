"""Tests for Resource.add_child() error path and Resource.restart().

Verifies:
- add_child() rejects an explicit 'parent' kwarg with a clear ValueError
- restart() shuts the resource down and re-initializes it, running both hook sets
"""

import pytest

from hassette.exceptions import RestartRefusedError
from hassette.resources.lifecycle import start
from hassette.resources.operations import restart
from hassette.types.enums import ResourceStatus
from tests.support.helpers import SHORT_SHUTDOWN_TIMEOUT_SECONDS
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ConcreteResource, wait_for_running
from .lifecycle.conftest import HangingChild, SimpleParent


class TrackedResource(ConcreteResource):
    """Resource that counts on_initialize/on_shutdown calls, for restart() verification."""

    init_count: int = 0
    shutdown_count: int = 0

    async def on_initialize(self) -> None:
        self.init_count += 1

    async def on_shutdown(self) -> None:
        self.shutdown_count += 1


class TestAddChildParentKwargRejected:
    def test_add_child_raises_when_parent_kwarg_supplied(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        parent = ConcreteResource(hassette=hassette)
        other = ConcreteResource(hassette=hassette)

        with pytest.raises(ValueError, match="Cannot specify 'parent' argument"):
            parent.add_child(ConcreteResource, parent=other)

        # No child should have been appended on the failed call.
        assert parent.children == []


class TestRestart:
    async def test_restart_shuts_down_and_reinitializes(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = TrackedResource(hassette=hassette)

        await resource.initialize()
        await wait_for_running(resource)
        assert resource.init_count == 1
        assert resource.shutdown_count == 0

        await restart(resource)

        assert resource.shutdown_count == 1, "restart() must run shutdown hooks before re-initializing"
        assert resource.init_count == 2, "restart() must run initialize hooks again"
        assert resource.status == ResourceStatus.RUNNING
        assert resource.shutdown_completed is False, "post-restart the resource should be live again"


class TestRestartRefusedAfterChildTimeout:
    """A child timeout that leaves the parent's stored report with ``is_restart_safe`` ``False`` must
    refuse every same-instance initialization path -- ``restart()``, ``start()``, and a direct
    ``initialize()`` call -- without running a second ``on_initialize()`` hook.
    """

    @staticmethod
    async def _make_unsafe_parent() -> SimpleParent:
        """Build a parent whose only child hangs forever during shutdown, then shut it down.

        The resulting report's exact cause depends on a race between ``_shutdown_children()``'s
        own bounded wait and the shutdown coordinator's whole-body deadline -- both read the same
        ``resource_shutdown_timeout_seconds`` config value, but the coordinator's clock starts
        earlier (as soon as the body task is created, before hooks/TaskBucket/cleanup even run),
        so it usually times out first and force-terminates the still-hanging child from the
        outside (``SHUTDOWN_BODY_TIMED_OUT``/``FORCED_TERMINAL``) rather than
        ``_shutdown_children()`` reaching its own ``CHILD_SHUTDOWN_TIMED_OUT`` first. Either path
        proves the same thing this test needs: a hanging child makes the parent's report
        restart-unsafe. See ``test_shutdown.py``'s dedicated
        ``test_shutdown_children_timeout_preserves_finished_safe_child_report`` for the specific
        ``CHILD_SHUTDOWN_TIMED_OUT`` cause, tested by calling ``_shutdown_children()`` directly to
        avoid this same race.
        """
        hassette = make_mock_hassette(sealed=False)
        hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

        parent = SimpleParent(hassette)
        hanging = parent.add_child(HangingChild)

        await parent.initialize()
        await hanging.initialize()

        report = await parent.shutdown()
        assert report.is_restart_safe is False
        return parent

    async def test_restart_raises_and_never_reinitializes(self) -> None:
        parent = await self._make_unsafe_parent()
        stored_report = parent.teardown_report

        with pytest.raises(RestartRefusedError) as exc_info:
            await restart(parent)

        assert exc_info.value.report is stored_report
        assert parent.teardown_report is stored_report, "refusal must not clear or replace the stored report"
        assert parent.status == ResourceStatus.STOPPED, "refusal must not run a second initialize hook"

    async def test_start_raises_and_never_reinitializes(self) -> None:
        parent = await self._make_unsafe_parent()
        stored_report = parent.teardown_report

        with pytest.raises(RestartRefusedError) as exc_info:
            start(parent)

        assert exc_info.value.report is stored_report
        assert parent.teardown_report is stored_report
        assert parent.status == ResourceStatus.STOPPED

    async def test_direct_initialize_raises_and_never_reinitializes(self) -> None:
        parent = await self._make_unsafe_parent()
        stored_report = parent.teardown_report

        with pytest.raises(RestartRefusedError) as exc_info:
            await parent.initialize()

        assert exc_info.value.report is stored_report
        assert parent.teardown_report is stored_report
        assert parent.status == ResourceStatus.STOPPED
