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

seq = itertools.count(1)


def next_id() -> int:
    return next(seq)


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
    """The name of the resource."""

    role: ResourceRole
    """The role of the resource, e.g. 'service', 'resource', 'app', etc."""

    status: ResourceStatus
    """The status of the resource, e.g. 'started', 'stopped', 'failed', etc."""

    previous_status: ResourceStatus | None = None
    """The previous status of the resource before the current status."""

    exception: str | None = None
    """Optional exception message if the service failed."""

    exception_type: str | None = None
    """Optional type of the exception if the service failed."""

    exception_traceback: str | None = None
    """Optional traceback of the exception if the service failed."""


@dataclass(slots=True, frozen=True)
class WebsocketStatusEventPayload:
    """Payload for websocket status events."""

    event_id: int = field(default_factory=next_id, init=False)

    connected: bool
    """Whether the websocket is connected or not."""

    url: str | None = None
    """The URL of the websocket server."""

    error: str | None = None
    """Optional error message if the websocket connection failed."""

    @classmethod
    def connected_payload(cls, url: str) -> "WebsocketStatusEventPayload":
        """Create a payload for a connected websocket event."""
        return cls(connected=True, url=url)

    @classmethod
    def disconnected_payload(cls, error: str) -> "WebsocketStatusEventPayload":
        """Create a payload for a disconnected websocket event."""
        return cls(connected=False, error=error)


@dataclass(slots=True, frozen=True)
class FileWatcherEventPayload:
    """Payload for file watcher events."""

    event_id: int = field(default_factory=next_id, init=False)

    changed_file_path: Path


def create_service_status_event(
    *,
    resource_name: str,
    role: ResourceRole,
    status: ResourceStatus,
    previous_status: ResourceStatus | None = None,
    exc: Exception | None = None,
) -> "HassetteServiceEvent":
    payload = ServiceStatusPayload(
        resource_name=resource_name,
        role=role,
        status=status,
        previous_status=previous_status,
        exception=str(exc) if exc else None,
        exception_type=type(exc).__name__ if exc else None,
        exception_traceback=get_traceback_string(exc) if exc else None,
    )

    return Event(
        topic=HASSETTE_EVENT_SERVICE_STATUS,
        payload=HassettePayload(event_type=str(status), data=payload),
    )


def create_websocket_status_event(
    connected: bool, url: str | None = None, error: str | None = None
) -> "HassetteWebsocketStatusEvent":
    """Create a websocket status event.

    Args:
        connected (bool): Whether the websocket is connected or not.
        url (str | None): The URL of the websocket server.
        error (str | None): Optional error message if the websocket connection failed.

    Returns:
        WebsocketStatusEvent: The created websocket status event.
    """
    if connected:
        if not url:
            raise ValueError("URL must be provided when connected is True")

        return Event(
            topic=HASSETTE_EVENT_WEBSOCKET_STATUS,
            payload=HassettePayload(event_type="connected", data=WebsocketStatusEventPayload.connected_payload(url)),
        )

    if not error:
        raise ValueError("Error message must be provided when connected is False")

    return Event(
        topic=HASSETTE_EVENT_WEBSOCKET_STATUS,
        payload=HassettePayload(
            event_type="disconnected", data=WebsocketStatusEventPayload.disconnected_payload(error)
        ),
    )


def create_file_watcher_event(
    changed_file_path: Path,
) -> "HassetteEvent":
    """Create a file watcher event.

    Args:
        changed_file_path (Path): The path of the changed file.

    Returns:
        FileWatcherEvent: The created file watcher event.
    """

    return Event(
        topic=HASSETTE_EVENT_FILE_WATCHER,
        payload=HassettePayload(
            event_type="file_changed", data=FileWatcherEventPayload(changed_file_path=changed_file_path)
        ),
    )


HassetteServiceEvent = Event[HassettePayload[ServiceStatusPayload]]
HassetteWebsocketStatusEvent = Event[HassettePayload[WebsocketStatusEventPayload]]
HassetteFileWatcherEvent = Event[HassettePayload[FileWatcherEventPayload]]
HassetteEvent = Event[HassettePayload[Any]]
