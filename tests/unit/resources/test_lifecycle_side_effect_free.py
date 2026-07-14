"""Tests verifying mark_ready/mark_not_ready remain side-effect-free."""

from hassette.resources.lifecycle import mark_not_ready, mark_ready
from hassette.test_utils import make_mock_hassette

from .conftest import ConcreteResource


class TestLifecycleSideEffectFree:
    """Verify mark_ready and mark_not_ready do NOT emit events."""

    async def test_mark_ready_does_not_emit(self) -> None:
        """mark_ready() must not call hassette.send_event."""
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)

        mark_ready(resource, "some reason")

        assert not hassette.send_event.called

    async def test_mark_not_ready_does_not_emit(self) -> None:
        """mark_not_ready() must not call hassette.send_event."""
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)

        # Set ready first, then clear
        mark_ready(resource, "initial")
        hassette.send_event.reset_mock()  # reset after mark_ready (which shouldn't call either)

        mark_not_ready(resource, "not ready")

        assert not hassette.send_event.called
