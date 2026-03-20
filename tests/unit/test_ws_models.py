"""Tests for typed WebSocket message models."""

from dataclasses import asdict

import pytest
from pydantic import TypeAdapter

from hassette.web.models import (
    AppStatusChangedPayload,
    AppStatusChangedWsMessage,
    ConnectedPayload,
    ConnectedWsMessage,
    ConnectivityWsMessage,
    LogWsMessage,
    ServiceStatusWsMessage,
    StateChangedPayload,
    StateChangedWsMessage,
    WsServerMessage,
    WsServiceStatusPayload,
)


class TestAppStatusChangedPayloadMatchesDataclass:
    """Verify AppStatusChangedPayload mirrors events.hassette.AppStateChangePayload."""

    def test_all_fields_present(self) -> None:
        from hassette.events.hassette import AppStateChangePayload
        from hassette.types.enums import ResourceStatus

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
        serialized = {k: str(v) if hasattr(v, "value") else v for k, v in asdict(dataclass_instance).items()}
        payload = AppStatusChangedPayload.model_validate(serialized)
        assert payload.app_key == "my_app"
        assert payload.index == 0
        assert payload.status == "ResourceStatus.RUNNING" or payload.status == "running"
        assert payload.instance_name == "my_app_0"
        assert payload.class_name == "MyApp"

    def test_optional_fields_default_to_none(self) -> None:
        payload = AppStatusChangedPayload(app_key="test", index=0, status="running")
        assert payload.previous_status is None
        assert payload.instance_name is None
        assert payload.class_name is None
        assert payload.exception is None
        assert payload.exception_type is None
        assert payload.exception_traceback is None


class TestServiceStatusPayloadMatchesDataclass:
    """Verify WsServiceStatusPayload mirrors events.hassette.ServiceStatusPayload."""

    def test_all_fields_present(self) -> None:
        from hassette.events.hassette import ServiceStatusPayload
        from hassette.types.enums import ResourceRole, ResourceStatus

        dataclass_instance = ServiceStatusPayload(
            resource_name="telemetry",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
            previous_status=ResourceStatus.STARTING,
        )
        serialized = {k: str(v) if hasattr(v, "value") else v for k, v in asdict(dataclass_instance).items()}
        payload = WsServiceStatusPayload.model_validate(serialized)
        assert payload.resource_name == "telemetry"


class TestStateChangedNormalizedEnvelope:
    """Verify state_changed uses the { type, data, timestamp } envelope."""

    def test_state_changed_has_data_wrapper(self) -> None:
        msg = StateChangedWsMessage(
            type="state_changed",
            data=StateChangedPayload(entity_id="light.kitchen", new_state={"state": "on"}, old_state={"state": "off"}),
            timestamp=1234567890.0,
        )
        dumped = msg.model_dump()
        assert "data" in dumped
        assert dumped["data"]["entity_id"] == "light.kitchen"
        assert "entity_id" not in dumped  # not at top level


class TestConnectedPayloadIncludesSessionId:
    """Verify ConnectedPayload includes session_id field."""

    def test_session_id_present(self) -> None:
        payload = ConnectedPayload(session_id=42, entity_count=10, app_count=3)
        assert payload.session_id == 42

    def test_session_id_optional(self) -> None:
        payload = ConnectedPayload(entity_count=10, app_count=3)
        assert payload.session_id is None


class TestWsServerMessageDiscriminates:
    """Verify WsServerMessage discriminated union narrows by type."""

    adapter = TypeAdapter(WsServerMessage)

    def test_app_status_changed(self) -> None:
        raw = {
            "type": "app_status_changed",
            "data": {"app_key": "my_app", "index": 0, "status": "running"},
            "timestamp": 1234567890.0,
        }
        msg = self.adapter.validate_python(raw)
        assert isinstance(msg, AppStatusChangedWsMessage)
        assert msg.data.app_key == "my_app"

    def test_log_message(self) -> None:
        raw = {
            "type": "log",
            "data": {
                "timestamp": 1234567890.0,
                "level": "INFO",
                "logger_name": "test",
                "func_name": "test_fn",
                "lineno": 1,
                "message": "hello",
            },
            "timestamp": 1234567890.0,
        }
        msg = self.adapter.validate_python(raw)
        assert isinstance(msg, LogWsMessage)
        assert msg.data.message == "hello"

    def test_connected(self) -> None:
        raw = {
            "type": "connected",
            "data": {"session_id": 1, "entity_count": 5, "app_count": 2},
            "timestamp": 1234567890.0,
        }
        msg = self.adapter.validate_python(raw)
        assert isinstance(msg, ConnectedWsMessage)
        assert msg.data.session_id == 1
        assert msg.timestamp == 1234567890.0

    def test_connectivity(self) -> None:
        raw = {"type": "connectivity", "data": {"connected": True}, "timestamp": 1234567890.0}
        msg = self.adapter.validate_python(raw)
        assert isinstance(msg, ConnectivityWsMessage)
        assert msg.data.connected is True

    def test_state_changed(self) -> None:
        raw = {
            "type": "state_changed",
            "data": {"entity_id": "light.kitchen", "new_state": {"state": "on"}, "old_state": {"state": "off"}},
            "timestamp": 1234567890.0,
        }
        msg = self.adapter.validate_python(raw)
        assert isinstance(msg, StateChangedWsMessage)
        assert msg.data.entity_id == "light.kitchen"

    def test_service_status(self) -> None:
        raw = {
            "type": "service_status",
            "data": {"resource_name": "telemetry", "role": "service", "status": "running"},
            "timestamp": 1234567890.0,
        }
        msg = self.adapter.validate_python(raw)
        assert isinstance(msg, ServiceStatusWsMessage)

    def test_invalid_type_raises(self) -> None:
        raw = {"type": "unknown_type", "data": {}, "timestamp": 1234567890.0}
        with pytest.raises(ValueError, match="does not match any of the expected tags"):
            self.adapter.validate_python(raw)
