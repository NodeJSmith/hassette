from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hassette.enums import ResourceRole, ResourceStatus
from hassette.events.base import Event, HassettePayload, HassetteT
from hassette.topics import (
    HASSETTE_EVENT_FILE_WATCHER,
    HASSETTE_EVENT_SERVICE_STATUS,
    HASSETTE_EVENT_WEBSOCKET_STATUS,
)
from hassette.utils.exception_utils import get_traceback_string


def _wrap_hassette_event(*, topic: str, payload: HassetteT, event_type: str) -> "Event[HassettePayload[HassetteT]]":
    return Event(topic=topic, payload=HassettePayload(event_type=event_type, data=payload))


@dataclass(slots=True, frozen=True)
class HassetteEmptyPayload:
    """Empty payload for events that do not require additional data."""

    @classmethod
    def create_event(cls, topic: str) -> "HassetteSimpleEvent":
        payload = cls()
        return _wrap_hassette_event(topic=topic, payload=payload, event_type="empty")


@dataclass(slots=True, frozen=True)
class ServiceStatusPayload:
    """Payload for service events."""

    resource_name: str
    role: ResourceRole
    status: ResourceStatus
    previous_status: ResourceStatus | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None

    @classmethod
    def create_event(
        cls,
        *,
        resource_name: str,
        role: ResourceRole,
        status: ResourceStatus,
        previous_status: ResourceStatus | None = None,
        exc: Exception | BaseException | None = None,
    ) -> "HassetteServiceEvent":
        payload = cls(
            resource_name=resource_name,
            role=role,
            status=status,
            previous_status=previous_status,
            exception=str(exc) if exc else None,
            exception_type=type(exc).__name__ if exc else None,
            exception_traceback=get_traceback_string(exc) if exc else None,
        )
        return _wrap_hassette_event(
            topic=HASSETTE_EVENT_SERVICE_STATUS,
            payload=payload,
            event_type=str(status),
        )


@dataclass(slots=True, frozen=True)
class WebsocketConnectedEventPayload:
    """Payload for websocket connected events."""

    url: str

    @classmethod
    def create_event(cls, *, url: str) -> "HassetteWebsocketConnectedEvent":
        payload = cls(url=url)
        return _wrap_hassette_event(
            topic=HASSETTE_EVENT_WEBSOCKET_STATUS,
            payload=payload,
            event_type="connected",
        )


@dataclass(slots=True, frozen=True)
class WebsocketDisconnectedEventPayload:
    """Payload for websocket disconnected events."""

    error: str

    @classmethod
    def create_event(cls, *, error: str) -> "HassetteWebsocketDisconnectedEvent":
        payload = cls(error=error)
        return _wrap_hassette_event(
            topic=HASSETTE_EVENT_WEBSOCKET_STATUS,
            payload=payload,
            event_type="disconnected",
        )


@dataclass(slots=True, frozen=True)
class FileWatcherEventPayload:
    """Payload for file watcher events."""

    changed_file_path: Path

    @classmethod
    def create_event(cls, *, changed_file_path: Path) -> "HassetteEvent":
        payload = cls(changed_file_path=changed_file_path)
        return _wrap_hassette_event(
            topic=HASSETTE_EVENT_FILE_WATCHER,
            payload=payload,
            event_type="file_changed",
        )


HassetteServiceEvent = Event[HassettePayload[ServiceStatusPayload]]
HassetteSimpleEvent = Event[HassettePayload[HassetteEmptyPayload]]
HassetteWebsocketConnectedEvent = Event[HassettePayload[WebsocketConnectedEventPayload]]
HassetteWebsocketDisconnectedEvent = Event[HassettePayload[WebsocketDisconnectedEventPayload]]
HassetteFileWatcherEvent = Event[HassettePayload[FileWatcherEventPayload]]
HassetteEvent = Event[HassettePayload[Any]]
