from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from hassette.events.base import Event, HassettePayload
from hassette.types import ResourceRole, ResourceStatus, Topic
from hassette.utils import get_traceback_string

if TYPE_CHECKING:
    from hassette import App


def _extract_exception_fields(
    exception: Exception | BaseException | None,
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
    """Payload for service events."""

    resource_name: str
    role: ResourceRole
    status: ResourceStatus
    previous_status: ResourceStatus | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None
    retry_at: float | None = None
    """Unix timestamp when the next restart will be attempted.
    Populated for EXHAUSTED_COOLING. None for EXHAUSTED_DEAD and all other statuses."""
    ready: bool = False
    """Whether the service has signalled readiness at the time of this status event."""
    ready_phase: str | None = None
    """Human-readable description of the current readiness phase, or None if not available."""


@dataclass(slots=True, frozen=True)
class FileWatcherEventPayload:
    """Payload for file watcher events."""

    changed_file_paths: frozenset[Path]


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
        ready: bool = False,
        ready_phase: str | None = None,
    ) -> "HassetteServiceEvent":
        exc_str, exc_type, exc_tb = _extract_exception_fields(exception)
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
    """Alias for simple events with empty payload."""

    @classmethod
    def create_event(cls, topic: Topic) -> "HassetteSimpleEvent":
        payload = HassetteEmptyPayload()
        return cls(
            topic=topic,
            payload=HassettePayload(data=payload),
        )


class HassetteFileWatcherEvent(Event[HassettePayload[FileWatcherEventPayload]]):
    """Alias for file watcher events."""

    @classmethod
    def create_event(cls, *, changed_file_paths: set[Path]) -> "HassetteFileWatcherEvent":
        payload = FileWatcherEventPayload(changed_file_paths=frozenset(changed_file_paths))
        return cls(
            topic=Topic.HASSETTE_EVENT_FILE_WATCHER,
            payload=HassettePayload(data=payload),
        )


@dataclass(slots=True, frozen=True)
class AppStateChangePayload:
    """Payload for app instance state change events."""

    app_key: str
    index: int
    status: ResourceStatus
    previous_status: ResourceStatus | None = None
    instance_name: str | None = None
    class_name: str | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None


class HassetteAppStateEvent(Event[HassettePayload[AppStateChangePayload]]):
    """Event emitted when an app instance changes state."""

    @classmethod
    def from_data(
        cls,
        app: "App",
        status: ResourceStatus,
        previous_status: ResourceStatus | None = None,
        exception: Exception | BaseException | None = None,
    ) -> "HassetteAppStateEvent":
        exc_str, exc_type, exc_tb = _extract_exception_fields(exception)
        payload = AppStateChangePayload(
            app_key=app.app_key,
            index=app.index,
            status=status,
            previous_status=previous_status,
            instance_name=app.instance_name,
            class_name=type(app).__name__,
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

    kind: Literal["handler", "job"]
    status: str
    duration_ms: float
    listener_id: int | None = None
    job_id: int | None = None
    app_key: str = ""
    instance_index: int = 0
    error_type: str | None = None
    thread_leaked: bool = False


class HassetteExecutionCompletedEvent(Event[HassettePayload[ExecutionCompletedPayload]]):
    """Event emitted after a scheduled job execution is persisted to telemetry."""

    @classmethod
    def from_record(
        cls,
        kind: Literal["handler", "job"],
        status: str,
        duration_ms: float,
        listener_id: int | None = None,
        job_id: int | None = None,
        app_key: str = "",
        instance_index: int = 0,
        error_type: str | None = None,
        thread_leaked: bool = False,
    ) -> "HassetteExecutionCompletedEvent":
        payload = ExecutionCompletedPayload(
            kind=kind,
            status=status,
            duration_ms=duration_ms,
            listener_id=listener_id,
            job_id=job_id,
            app_key=app_key,
            instance_index=instance_index,
            error_type=error_type,
            thread_leaked=thread_leaked,
        )
        return cls(
            topic=Topic.HASSETTE_EVENT_EXECUTION_COMPLETED,
            payload=HassettePayload(data=payload),
        )
