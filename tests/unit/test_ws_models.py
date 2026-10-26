"""Tests for typed WebSocket message models."""

import dataclasses
from dataclasses import asdict

import pytest
from hassette_wire import (
    AppStatusChangedData,
    AppStatusChangedWsMessage,
    ConnectedData,
    ConnectedWsMessage,
    ConnectivityWsMessage,
    ExecutionCompletedData,
    ExecutionCompletedWsMessage,
    ExecutionStatus,
    LogHintWsMessage,
    ResourceStatus,
    ServiceStatusData,
    ServiceStatusWsMessage,
    WsServerMessage,
)
from pydantic import TypeAdapter

from hassette.events.hassette import AppStateChangePayload, ExecutionCompletedPayload, ServiceStatusPayload
from hassette.types.enums import ResourceRole

TEST_TIMESTAMP = 1234567890.0

MESSAGE_ADAPTER = TypeAdapter(WsServerMessage)


def validate_envelope(msg_type: str, data: object) -> WsServerMessage:
    """Validate a raw WS envelope and return the message the discriminated union narrowed it to."""
    return MESSAGE_ADAPTER.validate_python({"type": msg_type, "data": data, "timestamp": TEST_TIMESTAMP})


class TestAppStatusChangedDataMatchesDataclass:
    """Verify AppStatusChangedData mirrors events.hassette.AppStateChangePayload."""

    def test_field_names_match(self) -> None:
        dataclass_fields = {f.name for f in dataclasses.fields(AppStateChangePayload)}
        assert dataclass_fields == set(AppStatusChangedData.model_fields)

    def test_all_fields_present(self) -> None:
        dataclass_instance = AppStateChangePayload(
            app_key="my_app",
            index=0,
            status=ResourceStatus.RUNNING,
            previous_status=ResourceStatus.STARTING,
            instance_name="my_app_0",
            class_name="MyApp",
            exception=None,
            exception_type=None,
            exception_traceback=None,
        )
        serialized = {k: (v.value if hasattr(v, "value") else v) for k, v in asdict(dataclass_instance).items()}
        data = AppStatusChangedData.model_validate(serialized)
        assert data.app_key == "my_app"
        assert data.index == 0
        assert data.status == ResourceStatus.RUNNING
        assert data.instance_name == "my_app_0"
        assert data.class_name == "MyApp"

    def test_optional_fields_default_to_none(self) -> None:
        data = AppStatusChangedData(app_key="test", index=0, status="running")
        assert data.previous_status is None
        assert data.instance_name is None
        assert data.class_name is None
        assert data.exception is None
        assert data.exception_type is None
        assert data.exception_traceback is None


class TestServiceStatusDataMatchesDataclass:
    """Verify ServiceStatusData mirrors events.hassette.ServiceStatusPayload."""

    def test_field_names_match(self) -> None:
        # `role` stays on the internal event (the server filters on it) but is not sent over the wire.
        dataclass_fields = {f.name for f in dataclasses.fields(ServiceStatusPayload)}
        assert dataclass_fields - {"role"} == set(ServiceStatusData.model_fields)

    def test_all_fields_present(self) -> None:
        dataclass_instance = ServiceStatusPayload(
            resource_name="telemetry",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
            previous_status=ResourceStatus.STARTING,
            ready=True,
            ready_phase="connected",
        )
        serialized = {k: (v.value if hasattr(v, "value") else v) for k, v in asdict(dataclass_instance).items()}
        data = ServiceStatusData.model_validate(serialized)
        assert data.resource_name == "telemetry"
        assert data.ready is True
        assert data.ready_phase == "connected"


class TestConnectedDataIncludesUptimeSeconds:
    """Verify ConnectedData includes uptime_seconds field."""

    def test_uptime_seconds_present(self) -> None:
        data = ConnectedData(uptime_seconds=123.4, entity_count=10, app_count=3)
        assert data.uptime_seconds == 123.4

    def test_uptime_seconds_zero(self) -> None:
        data = ConnectedData(uptime_seconds=0.0, entity_count=10, app_count=3)
        assert data.uptime_seconds == 0.0


class TestWsServerMessageDiscriminates:
    """Verify WsServerMessage discriminated union narrows by type."""

    def test_app_status_changed(self) -> None:
        msg = validate_envelope("app_status_changed", {"app_key": "my_app", "index": 0, "status": "running"})
        assert isinstance(msg, AppStatusChangedWsMessage)
        assert msg.data.app_key == "my_app"

    def test_log_hint_message(self) -> None:
        msg = MESSAGE_ADAPTER.validate_python({"type": "log_hint", "timestamp": TEST_TIMESTAMP})
        assert isinstance(msg, LogHintWsMessage)
        assert msg.timestamp == TEST_TIMESTAMP
        assert not hasattr(msg, "data")

    def test_connected(self) -> None:
        msg = validate_envelope("connected", {"uptime_seconds": 300.0, "entity_count": 5, "app_count": 2})
        assert isinstance(msg, ConnectedWsMessage)
        assert msg.data.uptime_seconds == 300.0
        assert msg.timestamp == TEST_TIMESTAMP

    def test_connectivity(self) -> None:
        msg = validate_envelope("connectivity", {"connected": True})
        assert isinstance(msg, ConnectivityWsMessage)
        assert msg.data.connected is True

    def test_service_status(self) -> None:
        msg = validate_envelope("service_status", {"resource_name": "telemetry", "status": "running"})
        assert isinstance(msg, ServiceStatusWsMessage)

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="does not match any of the expected tags"):
            validate_envelope("unknown_type", {})


class TestCompletionWsMessages:
    """execution_completed carries a unified list payload (per-drain batching, kind discriminates handler/job)."""

    def test_handler_execution_discriminates(self) -> None:
        msg = validate_envelope(
            "execution_completed",
            [
                {
                    "kind": "handler",
                    "listener_id": 1,
                    "app_key": "my_app",
                    "instance_index": 0,
                    "status": "success",
                    "duration_ms": 12.5,
                    "error_type": None,
                }
            ],
        )
        assert isinstance(msg, ExecutionCompletedWsMessage)
        assert len(msg.data) == 1
        assert msg.data[0].kind == "handler"
        assert msg.data[0].listener_id == 1
        assert msg.data[0].app_key == "my_app"
        assert msg.data[0].status == ExecutionStatus.SUCCESS
        assert msg.data[0].error_type is None

    def test_job_execution_discriminates(self) -> None:
        msg = validate_envelope(
            "execution_completed",
            [
                {
                    "kind": "job",
                    "job_id": 7,
                    "app_key": "scheduler_app",
                    "instance_index": 1,
                    "status": "error",
                    "duration_ms": 99.9,
                    "error_type": "TimeoutError",
                }
            ],
        )
        assert isinstance(msg, ExecutionCompletedWsMessage)
        assert len(msg.data) == 1
        assert msg.data[0].kind == "job"
        assert msg.data[0].job_id == 7
        assert msg.data[0].error_type == "TimeoutError"

    def test_execution_completed_empty_batch_valid(self) -> None:
        """An empty batch list is valid (schema must accept it even if flush skips empty batches)."""
        msg = validate_envelope("execution_completed", [])
        assert isinstance(msg, ExecutionCompletedWsMessage)
        assert msg.data == []

    def test_execution_completed_mixed_batch(self) -> None:
        """A batch may contain both handler and job entries in one message."""
        msg = validate_envelope(
            "execution_completed",
            [
                {
                    "kind": "handler",
                    "listener_id": 1,
                    "app_key": "a",
                    "instance_index": 0,
                    "status": "success",
                    "duration_ms": 1.0,
                },
                {
                    "kind": "job",
                    "job_id": 5,
                    "app_key": "b",
                    "instance_index": 1,
                    "status": "error",
                    "duration_ms": 2.0,
                    "error_type": "ValueError",
                },
            ],
        )
        assert isinstance(msg, ExecutionCompletedWsMessage)
        assert len(msg.data) == 2
        assert msg.data[0].kind == "handler"
        assert msg.data[1].kind == "job"
        assert msg.data[1].error_type == "ValueError"


class TestExecutionCompletedDataStatusIsClosedEnum:
    """Regression guard for the untyped ``ExecutionCompletedPayload.status: str`` producer chain.

    Before this fix, ``ExecutionRecord``/``ExecutionCompletedPayload``/``from_record()`` all
    typed ``status`` as a bare ``str`` even though ``ExecutionCompletedData`` (the strict wire
    model the frontend validates against) narrows it to the closed ``ExecutionStatus`` enum.
    Nothing guaranteed the producer chain could only emit one of the 5 real values — a stray
    string anywhere upstream would have silently discarded the *entire* execution_completed
    batch on the frontend (batch validation has no partial acceptance). Retyping the chain to
    ``ExecutionStatus`` makes an out-of-enum value a ``pyright`` error at every real call site
    instead of a latent runtime gap.
    """

    @pytest.mark.parametrize("status", list(ExecutionStatus))
    def test_every_execution_status_round_trips_through_wire_model(self, status: ExecutionStatus) -> None:
        """Every real ExecutionStatus member survives payload construction and strict validation."""
        payload = ExecutionCompletedPayload(
            kind="handler",
            status=status,
            duration_ms=5.0,
            listener_id=1,
            app_key="my_app",
            instance_index=0,
        )

        # The field genuinely holds an ExecutionStatus instance, not a bare str that merely
        # compares equal to one (dataclasses do not enforce field types at runtime).
        assert isinstance(payload.status, ExecutionStatus)

        # Round-trip through the strict Pydantic wire model the frontend validates against.
        data = ExecutionCompletedData.model_validate(asdict(payload))
        assert data.status == status
