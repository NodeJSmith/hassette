from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from hassette.events.base import Event, HassettePayload
from hassette.types.enums import ResourceRole, ResourceStatus
from hassette.types.topics import (
    HASSETTE_EVENT_FILE_WATCHER,
    HASSETTE_EVENT_SERVICE_STATUS,
    HASSETTE_EVENT_WEBSOCKET_STATUS,
)
from hassette.utils import get_traceback_string


@dataclass(slots=True, frozen=True)
class HassetteEmptyPayload:
    """Empty payload for events that do not require additional data."""

    pass


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


@dataclass(slots=True, frozen=True)
class WebsocketConnectedEventPayload:
    """Payload for websocket connected events."""

    url: str


@dataclass(slots=True, frozen=True)
class WebsocketDisconnectedEventPayload:
    """Payload for websocket disconnected events."""

    error: str


@dataclass(slots=True, frozen=True)
class FileWatcherEventPayload:
    """Payload for file watcher events."""

    changed_file_path: Path


class HassetteServiceEvent(Event[HassettePayload[ServiceStatusPayload]]):
    """Alias for service status events."""

    @classmethod
    def from_data(
        cls,
        resource_name: str,
        role: ResourceRole,
        status: ResourceStatus,
        previous_status: ResourceStatus | None = None,
        exception: Exception | BaseException | None = None,
    ) -> "HassetteServiceEvent":
        exc_str = str(exception) if exception else None
        exc_type = type(exception).__name__ if exception else None
        exc_tb = get_traceback_string(exception) if exception else None

        payload = ServiceStatusPayload(
            resource_name=resource_name,
            role=role,
            status=status,
            previous_status=previous_status,
            exception=exc_str,
            exception_type=exc_type,
            exception_traceback=exc_tb,
        )
        return cls(
            topic=HASSETTE_EVENT_SERVICE_STATUS,
            payload=HassettePayload(event_type=str(payload.status), data=payload),
        )


class HassetteSimpleEvent(Event[HassettePayload[HassetteEmptyPayload]]):
    """Alias for simple events with empty payload."""

    @classmethod
    def create_event(cls, topic: str) -> "HassetteSimpleEvent":
        payload = HassetteEmptyPayload()
        return cls(
            topic=topic,
            payload=HassettePayload(event_type="empty", data=payload),
        )


class HassetteWebsocketConnectedEvent(Event[HassettePayload[WebsocketConnectedEventPayload]]):
    """Alias for websocket connected events."""

    @classmethod
    def create_event(cls, *, url: str) -> "HassetteWebsocketConnectedEvent":
        payload = WebsocketConnectedEventPayload(url=url)
        return cls(
            topic=HASSETTE_EVENT_WEBSOCKET_STATUS,
            payload=HassettePayload(event_type="connected", data=payload),
        )


class HassetteWebsocketDisconnectedEvent(Event[HassettePayload[WebsocketDisconnectedEventPayload]]):
    """Alias for websocket disconnected events."""

    @classmethod
    def create_event(cls, *, error: str) -> "HassetteWebsocketDisconnectedEvent":
        payload = WebsocketDisconnectedEventPayload(error=error)
        return cls(
            topic=HASSETTE_EVENT_WEBSOCKET_STATUS,
            payload=HassettePayload(event_type="disconnected", data=payload),
        )


class HassetteFileWatcherEvent(Event[HassettePayload[FileWatcherEventPayload]]):
    """Alias for file watcher events."""

    @classmethod
    def create_event(cls, *, changed_file_path: Path) -> "HassetteFileWatcherEvent":
        payload = FileWatcherEventPayload(changed_file_path=changed_file_path)
        return cls(
            topic=HASSETTE_EVENT_FILE_WATCHER,
            payload=HassettePayload(event_type="file_changed", data=payload),
        )


HassetteEvent: TypeAlias = Event[HassettePayload[Any]]
"""Alias for generic Hassette events."""
