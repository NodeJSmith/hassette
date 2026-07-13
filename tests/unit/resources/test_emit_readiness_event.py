"""Tests for Resource._emit_readiness_event and readiness in lifecycle transitions."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from hassette.resources.lifecycle import handle_running, mark_ready
from hassette.test_utils import make_mock_hassette
from hassette.types.enums import ResourceStatus

from .conftest import ConcreteResource

if TYPE_CHECKING:
    from hassette.events.hassette import ServiceStatusPayload


async def make_resource() -> tuple[ConcreteResource, AsyncMock]:
    """Create a Resource instance with a stubbed hassette."""
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette=hassette)
    return resource, hassette


class TestEmitReadinessEvent:
    """Tests for Resource._emit_readiness_event()."""

    async def test_emit_readiness_event_sends_service_status(self) -> None:
        """_emit_readiness_event sends a service_status event with current readiness state."""
        resource, hassette = await make_resource()

        # Set up RUNNING state + readiness
        resource._status = ResourceStatus.RUNNING
        mark_ready(resource, "test reason")

        await resource._emit_readiness_event()

        assert hassette.send_event.called

        call_args = hassette.send_event.call_args
        event = call_args[0][0]
        payload: ServiceStatusPayload = event.payload.data

        assert payload.ready is True
        assert payload.ready_phase == "test reason"
        assert payload.status == ResourceStatus.RUNNING

    async def test_handle_running_includes_readiness(self) -> None:
        """handle_running emits an event carrying the current readiness state."""
        resource, hassette = await make_resource()

        # Resource is not ready before handle_running
        assert resource.is_ready() is False

        resource._previous_status = ResourceStatus.STARTING
        resource._status = ResourceStatus.STARTING

        await handle_running(resource)

        assert hassette.send_event.called
        call_args = hassette.send_event.call_args
        event = call_args[0][0]
        payload: ServiceStatusPayload = event.payload.data

        assert payload.ready is False
        assert payload.status == ResourceStatus.RUNNING
