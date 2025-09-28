import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

from hassette.core.enums import ResourceRole, ResourceStatus
from hassette.core.events import Event
from hassette.core.topics import (
    HASSETTE_EVENT_FILE_WATCHER,
    HASSETTE_EVENT_SERVICE_STATUS,
    HASSETTE_EVENT_WEBSOCKET_STATUS,
)
from hassette.utils import get_traceback_string

HassetteT = TypeVar("HassetteT", covariant=True)
PayloadT = TypeVar("PayloadT")

seq = itertools.count(1)


def next_id() -> int:
    return next(seq)


def _wrap_hassette_event(*, topic: str, payload: PayloadT, event_type: str) -> "Event[HassettePayload[PayloadT]]":
    return Event(topic=topic, payload=HassettePayload(event_type=event_type, data=payload))


@dataclass(slots=True, frozen=True)
class HassettePayload(Generic[HassetteT]):
    """Base class for Hassette event payloads."""

    event_type: str
    data: HassetteT


@dataclass(slots=True, frozen=True)
class ServiceStatusPayload:
    """Payload for service events."""

    event_id: int = field(default_factory=next_id, init=False)

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
        exc: Exception | None = None,
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
class WebsocketStatusEventPayload:
    """Payload for websocket status events."""

    event_id: int = field(default_factory=next_id, init=False)

    connected: bool
    url: str | None = None
    error: str | None = None

    @classmethod
    def connected_payload(cls, url: str) -> "WebsocketStatusEventPayload":
        return cls(connected=True, url=url)

    @classmethod
    def disconnected_payload(cls, error: str) -> "WebsocketStatusEventPayload":
        return cls(connected=False, error=error)

    @classmethod
    def connected_event(cls, url: str) -> "HassetteWebsocketStatusEvent":
        if not url:
            raise ValueError("URL must be provided for a connected websocket event")
        payload = cls.connected_payload(url)
        return _wrap_hassette_event(
            topic=HASSETTE_EVENT_WEBSOCKET_STATUS,
            payload=payload,
            event_type="connected",
        )

    @classmethod
    def disconnected_event(cls, error: str) -> "HassetteWebsocketStatusEvent":
        if not error:
            raise ValueError("Error message must be provided for a disconnected websocket event")
        payload = cls.disconnected_payload(error)
        return _wrap_hassette_event(
            topic=HASSETTE_EVENT_WEBSOCKET_STATUS,
            payload=payload,
            event_type="disconnected",
        )


@dataclass(slots=True, frozen=True)
class FileWatcherEventPayload:
    """Payload for file watcher events."""

    event_id: int = field(default_factory=next_id, init=False)

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
HassetteWebsocketStatusEvent = Event[HassettePayload[WebsocketStatusEventPayload]]
HassetteFileWatcherEvent = Event[HassettePayload[FileWatcherEventPayload]]
HassetteEvent = Event[HassettePayload[Any]]
