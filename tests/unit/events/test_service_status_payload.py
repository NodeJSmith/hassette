"""Tests for ServiceStatusPayload ready/ready_phase fields."""

from hassette.events.hassette import HassetteServiceEvent, ServiceStatusPayload
from hassette.types.enums import ResourceRole, ResourceStatus


class TestServiceStatusPayloadDefaults:
    """Verify ServiceStatusPayload defaults for new ready/ready_phase fields."""

    def test_service_status_payload_defaults(self) -> None:
        """Constructing with no ready/ready_phase produces False/None."""
        payload = ServiceStatusPayload(
            resource_name="my_service",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
        )
        assert payload.ready is False
        assert payload.ready_phase is None

    def test_service_status_payload_explicit(self) -> None:
        """Explicit ready=True, ready_phase='connected' passes through."""
        payload = ServiceStatusPayload(
            resource_name="my_service",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
            ready=True,
            ready_phase="connected",
        )
        assert payload.ready is True
        assert payload.ready_phase == "connected"


class TestFromServiceStatusIncludesReadyFields:
    """Verify HassetteServiceEvent.from_service_status threads ready/ready_phase fields."""

    def test_from_service_status_includes_ready_fields(self) -> None:
        """from_service_status with ready=True, ready_phase='test' carries both into payload."""
        event = HassetteServiceEvent.from_service_status(
            resource_name="my_service",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
            ready=True,
            ready_phase="test",
        )
        assert event.payload.data.ready is True
        assert event.payload.data.ready_phase == "test"

    def test_from_service_status_ready_defaults(self) -> None:
        """from_service_status without ready params defaults to ready=False, ready_phase=None."""
        event = HassetteServiceEvent.from_service_status(
            resource_name="my_service",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
        )
        assert event.payload.data.ready is False
        assert event.payload.data.ready_phase is None
