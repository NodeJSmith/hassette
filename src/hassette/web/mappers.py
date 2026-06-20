"""Mapping functions from core domain objects to web response models.

Each function converts a domain type (from ``hassette.schemas``) to the
appropriate Pydantic response model from ``hassette.web.models``. Web routes
call these instead of receiving pre-mapped response objects from
``RuntimeQueryService``.

Enum coercion note
------------------
``AppInstanceInfo.status`` is a ``ResourceStatus`` enum (``StrEnum``). Pydantic
coerces it directly — pass the enum value as-is. ``AppManifestInfo.status`` is a
``str`` with the 5-value ManifestStatus set; cast to ``ManifestStatus`` for pyright.
``ServiceInfo.status`` is a ``str`` with ResourceStatus values; cast for pyright.
"""

from typing import cast

from hassette.schemas.app_snapshots import AppFullSnapshot, AppInstanceInfo, AppStatusSnapshot
from hassette.schemas.domain_models import SystemStatus
from hassette.schemas.live_counts import LiveCounts
from hassette.schemas.telemetry_models import ListenerSummary
from hassette.types.enums import ResourceStatus, Topic
from hassette.web.models import (
    AppInstanceResponse,
    AppManifestListResponse,
    AppManifestResponse,
    AppStatusResponse,
    BootIssueResponse,
    ConnectedPayload,
    ListenerKind,
    ListenerWithSummary,
    ManifestStatus,
    ReadinessResponse,
    ServiceInfoResponse,
    SystemStatusResponse,
)
from hassette.web.telemetry_helpers import format_handler_summary


def instance_response_from(info: AppInstanceInfo) -> AppInstanceResponse:
    """Convert a single ``AppInstanceInfo`` to ``AppInstanceResponse``."""
    return AppInstanceResponse(
        app_key=info.app_key,
        index=info.index,
        instance_name=info.instance_name,
        class_name=info.class_name,
        status=info.status,  # ResourceStatus StrEnum — Pydantic coerces directly
        error_message=info.error_message,
        error_traceback=info.error_traceback,
        owner_id=info.owner_id,
    )


def app_status_response_from(snapshot: AppStatusSnapshot) -> AppStatusResponse:
    """Convert an ``AppStatusSnapshot`` to ``AppStatusResponse``.

    Merges ``snapshot.running`` and ``snapshot.failed`` into a single ``apps``
    list (running first, then failed).
    """
    apps = [instance_response_from(info) for info in snapshot.running + snapshot.failed]
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
        instances = [instance_response_from(inst) for inst in m.instances]
        manifests.append(
            AppManifestResponse(
                app_key=m.app_key,
                class_name=m.class_name,
                display_name=m.display_name,
                filename=m.filename,
                enabled=m.enabled,
                auto_loaded=m.auto_loaded,
                status=cast("ManifestStatus", m.status),  # AppManifestInfo.status is str
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
    boot_issues = [
        BootIssueResponse(severity=issue.severity, label=issue.label, detail=issue.detail)
        for issue in status.boot_issues
    ]
    services = [
        ServiceInfoResponse(
            name=svc.name,
            status=cast("ResourceStatus", svc.status),  # ServiceInfo.status is str
            role=svc.role,
            ready_phase=svc.ready_phase,
            retry_at=svc.retry_at,
        )
        for svc in status.services
    ]
    return SystemStatusResponse(
        status=status.status,
        websocket_connected=status.websocket_connected,
        uptime_seconds=status.uptime_seconds,
        entity_count=status.entity_count,
        app_count=status.app_count,
        services_running=status.services_running,
        services=services,
        version=status.version,
        boot_issues=boot_issues,
        log_records_dropped=status.log_records_dropped,
    )


def readiness_response_from(status: SystemStatus) -> ReadinessResponse:
    """Convert a ``SystemStatus`` domain object to ``ReadinessResponse``.

    Readiness is derived solely from the aggregate status: ready only when ``ok``.
    """
    return ReadinessResponse(status=status.status, ready=status.status == "ok")


def connected_payload_from(status: SystemStatus) -> ConnectedPayload:
    """Build a ``ConnectedPayload`` from a ``SystemStatus``.

    ``uptime_seconds`` is sourced from ``SystemStatus.uptime_seconds``, which
    is computed from the same ``_start_time`` used by ``GET /health``.
    """
    return ConnectedPayload(
        uptime_seconds=status.uptime_seconds,
        entity_count=status.entity_count,
        app_count=status.app_count,
        version=status.version,
    )


TOPIC_KIND_MAP: dict[str, ListenerKind] = {
    Topic.HASS_EVENT_STATE_CHANGED: "state change",
    Topic.HASS_EVENT_CALL_SERVICE: "service call",
}


def listener_kind_from_topic(topic: str) -> ListenerKind:
    for prefix, kind in TOPIC_KIND_MAP.items():
        if topic.startswith(prefix):
            return kind
    return "event"


def to_listener_with_summary(
    ls: ListenerSummary,
    live_counts: dict[int, LiveCounts] | None = None,
) -> ListenerWithSummary:
    """Convert a ``ListenerSummary`` to a ``ListenerWithSummary`` response model.

    Copies every field from the summary and appends a computed
    ``handler_summary`` string via :func:`~hassette.web.telemetry_helpers.format_handler_summary`.

    Args:
        ls: The persisted listener summary from the telemetry DB.
        live_counts: Live execution counts keyed by listener ``db_id``, sourced from the bus's
            in-memory guards. A listener with no live guard (e.g. retired) defaults to
            ``LiveCounts(0, 0, 0)``.
    """
    suppressed, dropped, backpressure_dropped = (live_counts or {}).get(ls.listener_id, LiveCounts(0, 0, 0))
    return ListenerWithSummary(
        listener_id=ls.listener_id,
        app_key=ls.app_key,
        instance_index=ls.instance_index,
        topic=ls.topic,
        listener_kind=listener_kind_from_topic(ls.topic),
        handler_method=ls.handler_method,
        total_invocations=ls.total_invocations,
        successful=ls.successful,
        failed=ls.failed,
        di_failures=ls.di_failures,
        cancelled=ls.cancelled,
        timed_out=ls.timed_out,
        thread_leaked=ls.thread_leaked,
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
        last_error_traceback=ls.last_error_traceback,
        source_tier=ls.source_tier,
        source_location=ls.source_location,
        registration_source=ls.registration_source,
        handler_summary=format_handler_summary(ls),
        immediate=ls.immediate,
        duration=ls.duration,
        entity_id=ls.entity_id,
        mode=ls.mode,
        suppressed_count=suppressed,
        dropped_count=dropped,
        backpressure_dropped_count=backpressure_dropped,
        backpressure=ls.backpressure,
    )
