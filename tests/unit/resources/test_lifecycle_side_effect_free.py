"""Tests verifying mark_ready/mark_not_ready remain side-effect-free."""

from hassette.test_utils import make_mock_hassette

from .conftest import ConcreteResource


class TestLifecycleSideEffectFree:
    """Verify mark_ready and mark_not_ready do NOT emit events."""

    async def test_mark_ready_does_not_emit(self) -> None:
        """mark_ready() must not call hassette.send_event."""
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)

        resource.mark_ready("some reason")

        # hassette.send_event must NOT have been called
        assert not hassette.send_event.called

    async def test_mark_not_ready_does_not_emit(self) -> None:
        """mark_not_ready() must not call hassette.send_event."""
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)

        # Set ready first, then clear
        resource.mark_ready("initial")
        hassette.send_event.reset_mock()  # reset after mark_ready (which shouldn't call either)

        resource.mark_not_ready("not ready")

        # hassette.send_event must NOT have been called
        assert not hassette.send_event.called
