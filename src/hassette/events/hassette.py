from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hassette_wire import ExecutionKind, ExecutionStatus, ResourceStatus

from hassette.events.base import Event, HassettePayload
from hassette.schemas.app_snapshots import AppInstanceInfo
from hassette.types import ResourceRole, Topic
from hassette.utils import get_traceback_string

if TYPE_CHECKING:
    from hassette import App


def extract_exception_fields(
    exception: BaseException | None,
) -> tuple[str | None, str | None, str | None]:
    """Extract (message, type_name, traceback) from an exception, or (None, None, None)."""
    if exception is None:
        return None, None, None
    return str(exception), type(exception).__name__, get_traceback_string(exception)


@dataclass(slots=True, frozen=True)
class HassetteEmptyPayload:
    """Empty payload for events that do not require additional data."""


@dataclass(slots=True, frozen=True)
class ServiceStatusPayload:
    """Payload for service events.

    Exceptions are flattened to strings so the payload stays serialisable for WebSocket clients.
    """

    resource_name: str
    role: ResourceRole
    status: ResourceStatus
    previous_status: ResourceStatus | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None
    ready: bool = False
    """Whether the service has signalled readiness at the time of this status event."""
    ready_phase: str | None = None
    """Human-readable description of the current readiness phase, or None if not available."""


@dataclass(slots=True, frozen=True)
class FileWatcherEventPayload:
    """Payload for file watcher events."""

    changed_file_paths: frozenset[Path]


class HassetteServiceEvent(Event[HassettePayload[ServiceStatusPayload]]):
    """Event carrying service status changes."""

    @classmethod
    def from_service_status(
        cls,
        resource_name: str,
        role: ResourceRole,
        status: ResourceStatus,
        previous_status: ResourceStatus | None = None,
        exception: BaseException | None = None,
        ready: bool = False,
        ready_phase: str | None = None,
    ) -> "HassetteServiceEvent":
        """Build a service status event on the service-status topic.

        Args:
            resource_name: Name of the resource whose status changed.
            role: The resource's role.
            status: The new status.
            previous_status: The status before this change, if known.
            exception: The exception behind a failure, flattened into string, type, and traceback fields.
            ready: Whether the resource has signalled readiness.
            ready_phase: Description of the current readiness phase, if any.

        Returns:
            The event, ready to send on the bus.
        """
        exc_str, exc_type, exc_tb = extract_exception_fields(exception)
        payload = ServiceStatusPayload(
            resource_name=resource_name,
            role=role,
            status=status,
            previous_status=previous_status,
            exception=exc_str,
            exception_type=exc_type,
            exception_traceback=exc_tb,
            ready=ready,
            ready_phase=ready_phase,
        )
        return cls(
            topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
            payload=HassettePayload(data=payload),
        )


class HassetteSimpleEvent(Event[HassettePayload[HassetteEmptyPayload]]):
    """Event with an empty payload, published on a caller-chosen topic."""

    @classmethod
    def from_topic(cls, topic: Topic) -> "HassetteSimpleEvent":
        """Build an event on `topic` that carries an empty payload.

        Args:
            topic: The topic to publish on.

        Returns:
            The event, ready to send on the bus.
        """
        payload = HassetteEmptyPayload()
        return cls(
            topic=topic,
            payload=HassettePayload(data=payload),
        )


class HassetteFileWatcherEvent(Event[HassettePayload[FileWatcherEventPayload]]):
    """Event carrying the set of changed file paths."""

    @classmethod
    def from_paths(cls, *, changed_file_paths: set[Path]) -> "HassetteFileWatcherEvent":
        """Build a file watcher event on the file-watcher topic.

        Args:
            changed_file_paths: Paths that changed; stored as a frozenset in the payload.

        Returns:
            The event, ready to send on the bus.
        """
        payload = FileWatcherEventPayload(changed_file_paths=frozenset(changed_file_paths))
        return cls(
            topic=Topic.HASSETTE_EVENT_FILE_WATCHER,
            payload=HassettePayload(data=payload),
        )


@dataclass(slots=True, frozen=True)
class AppStateChangePayload:
    """Payload for app instance state change events.

    Exceptions are flattened to strings so the payload stays serialisable for WebSocket clients.
    """

    app_key: str
    instance_name: str
    status: ResourceStatus
    previous_status: ResourceStatus | None = None
    class_name: str | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None


class HassetteAppStateEvent(Event[HassettePayload[AppStateChangePayload]]):
    """Event emitted when an app instance changes state."""

    @classmethod
    def from_app(
        cls,
        app: "App",
        status: ResourceStatus,
        previous_status: ResourceStatus | None = None,
        exception: BaseException | None = None,
    ) -> "HassetteAppStateEvent":
        """Build an app state-change event from a live ``App`` instance.

        The app's key, instance name, and class name fill the payload's identity fields.

        Args:
            app: The app instance whose status changed.
            status: The new status.
            previous_status: The status before this change, if known.
            exception: The exception behind a failure, flattened into string, type, and traceback fields.

        Returns:
            The event, ready to send on the bus.
        """
        exc_str, exc_type, exc_tb = extract_exception_fields(exception)
        payload = AppStateChangePayload(
            app_key=app.app_key,
            instance_name=app.instance_name,
            status=status,
            previous_status=previous_status,
            class_name=type(app).__name__,
            exception=exc_str,
            exception_type=exc_type,
            exception_traceback=exc_tb,
        )
        return cls(
            topic=Topic.HASSETTE_EVENT_APP_STATE_CHANGED,
            payload=HassettePayload(data=payload),
        )

    @classmethod
    def from_instance_info(
        cls,
        info: AppInstanceInfo,
        status: ResourceStatus | None = None,
        previous_status: ResourceStatus | None = None,
    ) -> "HassetteAppStateEvent":
        """Build a state-change event from a registry snapshot entry, for paths where no ``App`` object exists.

        Exception fields are populated only when the resolved status is FAILED, so a STOPPED event for a
        removed failed entry doesn't look like a failed stop.

        Args:
            info: The registry entry for the app instance.
            status: The status to emit. Defaults to ``info.status``; pass it explicitly when the emitted
                status differs from the recorded one.
            previous_status: The status before this change, if known.

        Returns:
            The event, ready to send on the bus.
        """
        resolved_status = status if status is not None else info.status
        include_exception = resolved_status == ResourceStatus.FAILED
        exc_str, exc_type, exc_tb = extract_exception_fields(info.error if include_exception else None)
        payload = AppStateChangePayload(
            app_key=info.app_key,
            instance_name=info.instance_name,
            status=resolved_status,
            previous_status=previous_status,
            class_name=info.class_name,
            exception=exc_str,
            exception_type=exc_type,
            exception_traceback=exc_tb,
        )
        return cls(
            topic=Topic.HASSETTE_EVENT_APP_STATE_CHANGED,
            payload=HassettePayload(data=payload),
        )


@dataclass(slots=True, frozen=True)
class ExecutionCompletedPayload:
    """Payload for a completed execution — handler invocation or scheduled job.

    ``kind`` distinguishes the two: ``listener_id`` is set when ``kind == "handler"``,
    ``job_id`` when ``kind == "job"``.
    """

    kind: ExecutionKind
    status: ExecutionStatus
    duration_ms: float
    listener_id: int | None = None
    job_id: int | None = None
    app_key: str = ""
    error_type: str | None = None
    thread_leaked: bool = False


class HassetteExecutionCompletedEvent(Event[HassettePayload[ExecutionCompletedPayload]]):
    """Event emitted after a handler invocation or scheduled job execution is persisted to telemetry."""

    @classmethod
    def from_record(
        cls,
        kind: ExecutionKind,
        status: ExecutionStatus,
        duration_ms: float,
        listener_id: int | None = None,
        job_id: int | None = None,
        app_key: str = "",
        error_type: str | None = None,
        thread_leaked: bool = False,
    ) -> "HassetteExecutionCompletedEvent":
        """Build an execution-completed event from a persisted execution record's fields.

        Each argument maps one-to-one onto the matching ``ExecutionCompletedPayload`` field.

        Returns:
            The event, ready to send on the bus.
        """
        payload = ExecutionCompletedPayload(
            kind=kind,
            status=status,
            duration_ms=duration_ms,
            listener_id=listener_id,
            job_id=job_id,
            app_key=app_key,
            error_type=error_type,
            thread_leaked=thread_leaked,
        )
        return cls(
            topic=Topic.HASSETTE_EVENT_EXECUTION_COMPLETED,
            payload=HassettePayload(data=payload),
        )
