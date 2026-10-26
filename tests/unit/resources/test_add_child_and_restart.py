"""Tests for Resource.add_child()'s error paths and same-instance re-initialization.

Verifies:
- add_child() rejects an explicit 'parent' kwarg with a clear ValueError
- add_child() rejects a required Service under any parent but Hassette (spec 134 D17)
- shutdown() then initialize() runs both hook sets again after a clean teardown
- an unsafe teardown refuses every same-instance initialization path
"""

from typing import ClassVar

import pytest
from hassette_wire import ResourceStatus

from hassette.exceptions import RestartRefusedError
from hassette.resources.lifecycle import start
from hassette.resources.service import Service
from tests.support.helpers import SHORT_SHUTDOWN_TIMEOUT_SECONDS
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ConcreteResource, wait_for_running
from .lifecycle.conftest import HangingChild, SimpleParent


class TrackedResource(ConcreteResource):
    """Resource that counts on_initialize/on_shutdown calls, for re-initialization verification."""

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


class _RequiredChildService(Service):
    required: ClassVar[bool] = True

    async def serve(self) -> None:
        await self.shutdown_event.wait()


class _OptionalChildService(Service):
    required: ClassVar[bool] = False

    async def serve(self) -> None:
        await self.shutdown_event.wait()


class TestAddChildRequiredServiceParent:
    def test_rejects_required_service_under_a_non_hassette_parent(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        parent = ConcreteResource(hassette=hassette)

        with pytest.raises(ValueError, match="required service and can only be a child of Hassette"):
            parent.add_child(_RequiredChildService)

        assert parent.children == []

    def test_accepts_optional_service_under_any_parent(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        parent = ConcreteResource(hassette=hassette)

        child = parent.add_child(_OptionalChildService)

        assert parent.children == [child]

    def test_accepts_required_service_under_hassette(self) -> None:
        """Hassette is the one parent whose ``hassette`` is itself."""
        hassette = make_mock_hassette(sealed=False)
        hassette.hassette = hassette

        _RequiredChildService._validate_parent(hassette)


class TestReinitializeAfterCleanTeardown:
    async def test_shutdown_then_initialize_runs_both_hook_sets(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = TrackedResource(hassette=hassette)

        await resource.initialize()
        await wait_for_running(resource)
        assert resource.init_count == 1
        assert resource.shutdown_count == 0

        await resource.shutdown()
        await resource.initialize()

        assert resource.shutdown_count == 1
        assert resource.init_count == 2
        assert resource.status == ResourceStatus.RUNNING
        assert resource.shutdown_completed is False, "after re-initializing the resource should be live again"


class TestRestartRefusedAfterChildTimeout:
    """A child hook timeout that leaves the parent's stored report with ``is_restart_safe`` ``False`` must
    refuse every same-instance initialization path -- ``start()`` and a direct ``initialize()`` call --
    without running a second ``on_initialize()`` hook.
    """

    @staticmethod
    async def _make_unsafe_parent() -> SimpleParent:
        """Build a parent whose only child hangs during shutdown, then shut it down.

        The child's hook is cut off at its bound (``SHUTDOWN_HOOK_TIMED_OUT``), which makes the
        parent's merged report restart-unsafe.
        """
        hassette = make_mock_hassette(sealed=False)
        hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

        parent = SimpleParent(hassette)
        hanging = parent.add_child(HangingChild)

        await parent.initialize()
        await hanging.initialize()

        report = await parent.shutdown()
        assert report.is_restart_safe is False
        return parent

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
