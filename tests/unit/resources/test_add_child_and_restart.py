"""Tests for Resource.add_child() error path and Resource.restart().

Verifies:
- add_child() rejects an explicit 'parent' kwarg with a clear ValueError
- restart() shuts the resource down and re-initializes it, running both hook sets
"""

import pytest

from hassette.test_utils import make_mock_hassette, wait_for
from hassette.types.enums import ResourceStatus

from .conftest import ConcreteResource


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
        await wait_for(lambda: resource.status == ResourceStatus.RUNNING, desc="initial RUNNING")
        assert resource.init_count == 1
        assert resource.shutdown_count == 0

        await resource.restart()

        assert resource.shutdown_count == 1, "restart() must run shutdown hooks before re-initializing"
        assert resource.init_count == 2, "restart() must run initialize hooks again"
        assert resource.status == ResourceStatus.RUNNING
        assert resource.shutdown_completed is False, "post-restart the resource should be live again"
