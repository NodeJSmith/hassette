from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hassette_wire import ExecutionKind, ExecutionStatus, ResourceStatus

from hassette.events.base import Event, HassettePayload
from hassette.schemas.app_snapshots import NeedsRestartInfo
from hassette.types import ResourceRole, Topic
from hassette.utils import get_traceback_string

if TYPE_CHECKING:
    from hassette.core.app_registry import StatusChange


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
        return cls(
            topic=topic,
            payload=HassettePayload(data=HassetteEmptyPayload()),
        )


@dataclass(slots=True, frozen=True)
class FileWatcherEventPayload:
    """Payload for file watcher events."""

    changed_file_paths: frozenset[Path]


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
class IntegrationCommandPayload:
    """A press of an app-declared button, or a toggle of an app-declared switch.

    ``value`` is the commanded state for a switch and ``None`` for a button.
    """

    app_key: str
    instance_name: str
    key: str
    platform: str
    value: bool | None = None


class IntegrationCommandEvent(Event[HassettePayload[IntegrationCommandPayload]]):
    """Event that runs the handler an app instance declared for one of its buttons or switches.

    Published by ``IntegrationService.dispatch_command`` once ``admit_command`` finds the instance's live owner
    and the declared key.

    A switch handler reads the commanded value with ``D.SwitchCommand``.
    """

    @classmethod
    def create(
        cls, *, app_key: str, instance_name: str, key: str, platform: str, value: bool | None = None
    ) -> "IntegrationCommandEvent":
        """Build a command event on the integration-command topic.

        Args:
            app_key: The app key of the instance that declared the button or switch.
            instance_name: The instance name of the declaring app instance.
            key: The declared key of the button or switch.
            platform: The Home Assistant platform of the declared key, ``button`` or ``switch``.
            value: The commanded switch state, or ``None`` for a button.

        Returns:
            The event, ready to send on the bus.
        """
        payload = IntegrationCommandPayload(
            app_key=app_key, instance_name=instance_name, key=key, platform=platform, value=value
        )
        return cls(topic=Topic.HASSETTE_EVENT_INTEGRATION_COMMAND, payload=HassettePayload(data=payload))


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
    needs_restart: NeedsRestartInfo | None = None
    """Set on a FAILED change when the instance is flagged needs-restart: its teardown may have left work
    running, so it won't start again until hassette restarts.
    """


class HassetteAppStateEvent(Event[HassettePayload[AppStateChangePayload]]):
    """Event emitted when an app instance changes state."""

    @classmethod
    def from_change(cls, change: "StatusChange") -> "HassetteAppStateEvent":
        """Build an app state-change event from a transition ``AppRegistry.set_status`` applied.

        Identity and class name come from the change. Exception fields are filled from ``change.error``, and
        ``needs_restart`` from ``change.needs_restart``; only a FAILED change carries either.

        Args:
            change: The transition to report.

        Returns:
            The event, ready to send on the bus.
        """
        return cls.from_app_status(
            app_key=change.app_key,
            instance_name=change.instance_name,
            class_name=change.class_name,
            status=change.status,
            previous_status=change.previous,
            exception=change.error,
            needs_restart=change.needs_restart,
        )

    @classmethod
    def from_app_status(
        cls,
        app_key: str,
        instance_name: str,
        class_name: str,
        status: ResourceStatus,
        previous_status: ResourceStatus | None = None,
        exception: BaseException | None = None,
        needs_restart: NeedsRestartInfo | None = None,
    ) -> "HassetteAppStateEvent":
        """Build an app state-change event from its fields.

        ``from_change`` uses it, and so does the test harness, which simulates transitions no registry applied.

        Args:
            app_key: The app key.
            instance_name: The instance name.
            class_name: The app's class name.
            status: The new status.
            previous_status: The status before this change, if known.
            exception: The exception behind a failure, flattened into string, type, and traceback fields.
            needs_restart: The needs-restart flag a FAILED change carries, if any.

        Returns:
            The event, ready to send on the bus.
        """
        exc_str, exc_type, exc_tb = extract_exception_fields(exception)
        payload = AppStateChangePayload(
            app_key=app_key,
            instance_name=instance_name,
            status=status,
            previous_status=previous_status,
            class_name=class_name,
            exception=exc_str,
            exception_type=exc_type,
            exception_traceback=exc_tb,
            needs_restart=needs_restart,
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
