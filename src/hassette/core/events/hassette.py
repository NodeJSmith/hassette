import itertools
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar

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

    orphaned_apps: set[str] = field(default_factory=set)
    new_apps: set[str] = field(default_factory=set)
    reimport_apps: set[str] = field(default_factory=set)
    reload_apps: set[str] = field(default_factory=set)
    config_changes: dict[str, Any] = field(default_factory=dict)


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
    event_type: Literal["orphaned_apps", "new_apps", "reimport_apps", "reload_apps"],
    orphaned_apps: set[str] | None = None,
    new_apps: set[str] | None = None,
    reimport_apps: set[str] | None = None,
    reload_apps: set[str] | None = None,
    config_changes: dict[str, Any] | None = None,
) -> "HassetteEvent":
    """Create a file watcher event.

    Args:
        orphaned_apps (set[str]): Set of orphaned app names.
        new_apps (set[str]): Set of new app names.
        reimport_apps (set[str]): Set of app names that need to be reimported.
        reload_apps (set[str]): Set of app names that need to be reloaded.
        config_changes (dict[str, Any]): Dictionary of configuration changes.

    Returns:
        FileWatcherEvent: The created file watcher event.
    """
    orphaned_apps = orphaned_apps or set()
    new_apps = new_apps or set()
    reimport_apps = reimport_apps or set()
    reload_apps = reload_apps or set()
    config_changes = config_changes or {}

    payload = FileWatcherEventPayload(
        orphaned_apps=orphaned_apps,
        new_apps=new_apps,
        reimport_apps=reimport_apps,
        reload_apps=reload_apps,
        config_changes=config_changes,
    )

    return Event(
        topic=HASSETTE_EVENT_FILE_WATCHER,
        payload=HassettePayload(event_type=event_type, data=payload),
    )


HassetteServiceEvent = Event[HassettePayload[ServiceStatusPayload]]
HassetteWebsocketStatusEvent = Event[HassettePayload[WebsocketStatusEventPayload]]
HassetteFileWatcherEvent = Event[HassettePayload[FileWatcherEventPayload]]
HassetteEvent = Event[HassettePayload[Any]]
