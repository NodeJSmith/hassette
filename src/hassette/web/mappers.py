"""Mapping functions from core domain objects to web response models.

Each function converts a core domain type (from ``hassette.core``) to the
appropriate Pydantic response model from ``hassette.web.models``. Web routes
call these instead of receiving pre-mapped response objects from
``RuntimeQueryService``.

Enum coercion note
------------------
``AppInstanceInfo.status`` is a ``ResourceStatus`` enum (``StrEnum``). Call
``.value`` to get the plain string. ``AppManifestInfo.status`` is already a
``str`` — do not call ``.value`` on it.
"""

from hassette.core.app_registry import AppFullSnapshot, AppInstanceInfo, AppStatusSnapshot
from hassette.core.domain_models import SystemStatus
from hassette.core.telemetry_models import ListenerSummary
from hassette.web.models import (
    AppInstanceResponse,
    AppManifestListResponse,
    AppManifestResponse,
    AppStatusResponse,
    ConnectedPayload,
    ListenerWithSummary,
    SystemStatusResponse,
)
from hassette.web.telemetry_helpers import format_handler_summary


def _instance_response_from(info: AppInstanceInfo) -> AppInstanceResponse:
    """Convert a single ``AppInstanceInfo`` to ``AppInstanceResponse``."""
    return AppInstanceResponse(
        app_key=info.app_key,
        index=info.index,
        instance_name=info.instance_name,
        class_name=info.class_name,
        status=info.status.value,  # ResourceStatus enum → str
        error_message=info.error_message,
        error_traceback=info.error_traceback,
        owner_id=info.owner_id,
    )


def app_status_response_from(snapshot: AppStatusSnapshot) -> AppStatusResponse:
    """Convert an ``AppStatusSnapshot`` to ``AppStatusResponse``.

    Merges ``snapshot.running`` and ``snapshot.failed`` into a single ``apps``
    list (running first, then failed).
    """
    apps = [_instance_response_from(info) for info in snapshot.running + snapshot.failed]
    return AppStatusResponse(
        total=snapshot.total_count,
        running=snapshot.running_count,
        failed=snapshot.failed_count,
        apps=apps,
        only_app=snapshot.only_app,
    )


def app_manifest_list_response_from(full: AppFullSnapshot) -> AppManifestListResponse:
    """Convert an ``AppFullSnapshot`` to ``AppManifestListResponse``.

    Builds nested ``AppInstanceResponse`` objects from each manifest's
    ``instances`` list. ``AppInstanceInfo.status`` is a ``ResourceStatus``
    enum and requires ``.value``; ``AppManifestInfo.status`` is already a
    plain ``str``.
    """
    manifests = []
    for m in full.manifests:
        instances = [_instance_response_from(inst) for inst in m.instances]
        manifests.append(
            AppManifestResponse(
                app_key=m.app_key,
                class_name=m.class_name,
                display_name=m.display_name,
                filename=m.filename,
                enabled=m.enabled,
                auto_loaded=m.auto_loaded,
                status=m.status,  # already str — no .value
                block_reason=m.block_reason,
                instance_count=m.instance_count,
                instances=instances,
                error_message=m.error_message,
                error_traceback=m.error_traceback,
            )
        )
    return AppManifestListResponse(
        total=full.total,
        running=full.running,
        failed=full.failed,
        stopped=full.stopped,
        disabled=full.disabled,
        blocked=full.blocked,
        manifests=manifests,
        only_app=full.only_app,
    )


def system_status_response_from(status: SystemStatus) -> SystemStatusResponse:
    """Convert a ``SystemStatus`` domain object to ``SystemStatusResponse``."""
    return SystemStatusResponse(
        status=status.status,
        websocket_connected=status.websocket_connected,
        uptime_seconds=status.uptime_seconds,
        entity_count=status.entity_count,
        app_count=status.app_count,
        services_running=status.services_running,
    )


def connected_payload_from(status: SystemStatus, session_id: int | None) -> ConnectedPayload:
    """Build a ``ConnectedPayload`` from a ``SystemStatus`` and session ID.

    ``session_id`` is not part of ``SystemStatus`` — it must be obtained by
    the caller (e.g. via ``safe_session_id()``) and passed as a separate
    argument.
    """
    return ConnectedPayload(
        session_id=session_id,
        entity_count=status.entity_count,
        app_count=status.app_count,
    )


def to_listener_with_summary(ls: ListenerSummary) -> ListenerWithSummary:
    """Convert a ``ListenerSummary`` to a ``ListenerWithSummary`` response model.

    Copies every field from the summary and appends a computed
    ``handler_summary`` string via :func:`~hassette.web.telemetry_helpers.format_handler_summary`.
    """
    return ListenerWithSummary(
        listener_id=ls.listener_id,
        app_key=ls.app_key,
        instance_index=ls.instance_index,
        topic=ls.topic,
        handler_method=ls.handler_method,
        total_invocations=ls.total_invocations,
        successful=ls.successful,
        failed=ls.failed,
        di_failures=ls.di_failures,
        cancelled=ls.cancelled,
        avg_duration_ms=ls.avg_duration_ms,
        min_duration_ms=ls.min_duration_ms,
        max_duration_ms=ls.max_duration_ms,
        total_duration_ms=ls.total_duration_ms,
        predicate_description=ls.predicate_description,
        human_description=ls.human_description,
        debounce=ls.debounce,
        throttle=ls.throttle,
        once=ls.once,
        priority=ls.priority,
        last_invoked_at=ls.last_invoked_at,
        last_error_message=ls.last_error_message,
        last_error_type=ls.last_error_type,
        source_location=ls.source_location,
        registration_source=ls.registration_source,
        handler_summary=format_handler_summary(ls),
    )
