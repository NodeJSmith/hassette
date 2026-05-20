"""Tests verifying mark_ready/mark_not_ready remain side-effect-free."""

import pytest

from hassette.resources.base import Resource
from hassette.test_utils import make_mock_hassette


class _ConcreteResource(Resource):
    """Minimal concrete Resource subclass for testing."""

    async def on_initialize(self) -> None:
        pass


class TestLifecycleSideEffectFree:
    """Verify mark_ready and mark_not_ready do NOT emit events."""

    @pytest.mark.asyncio
    async def test_mark_ready_does_not_emit(self) -> None:
        """mark_ready() must not call hassette.send_event."""
        hassette = make_mock_hassette(sealed=False)
        resource = _ConcreteResource(hassette=hassette)

        resource.mark_ready("some reason")

        # hassette.send_event must NOT have been called
        assert not hassette.send_event.called

    @pytest.mark.asyncio
    async def test_mark_not_ready_does_not_emit(self) -> None:
        """mark_not_ready() must not call hassette.send_event."""
        hassette = make_mock_hassette(sealed=False)
        resource = _ConcreteResource(hassette=hassette)

        # Set ready first, then clear
        resource.mark_ready("initial")
        hassette.send_event.reset_mock()  # reset after mark_ready (which shouldn't call either)

        resource.mark_not_ready("not ready")

        # hassette.send_event must NOT have been called
        assert not hassette.send_event.called
