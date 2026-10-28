"""Tests for skipping a resource's own shutdown hooks while keeping framework stages and child shutdown."""

from hassette.resources import lifecycle
from hassette.resources.base import Resource
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ShutdownCounter


class HookRecordingParent(Resource):
    """Parent that records which of its own shutdown hooks and framework stages ran."""

    def __init__(self, hassette) -> None:
        super().__init__(hassette)
        self.ran: list[str] = []

    async def before_shutdown(self) -> None:
        self.ran.append("before_shutdown")

    async def on_shutdown(self) -> None:
        self.ran.append("on_shutdown")

    async def after_shutdown(self) -> None:
        self.ran.append("after_shutdown")

    async def cleanup(self) -> None:
        self.ran.append("cleanup")


async def test_skipping_own_shutdown_hooks_keeps_framework_stages_and_children():
    """With the skip set, the resource's own hooks don't run, but cleanup() and its children's shutdown
    (including the children's own hooks) still do.
    """
    hassette = make_mock_hassette(sealed=False)
    parent = HookRecordingParent(hassette)
    child = parent.add_child(ShutdownCounter)
    await parent.initialize()

    lifecycle.skip_own_shutdown_hooks(parent)
    await parent.shutdown()

    assert parent.ran == ["cleanup"]
    assert child.shutdown_count == 1, "the skip is not propagated to children"


async def test_hook_skip_resets_with_the_next_accepted_initialization():
    """The skip is per-attempt state: a new initialization after a clean teardown clears it."""
    hassette = make_mock_hassette(sealed=False)
    resource = HookRecordingParent(hassette)
    await resource.initialize()
    lifecycle.skip_own_shutdown_hooks(resource)
    await resource.shutdown()

    await resource.initialize()
    await resource.shutdown()

    assert resource.ran == ["cleanup", "before_shutdown", "on_shutdown", "after_shutdown", "cleanup"]
