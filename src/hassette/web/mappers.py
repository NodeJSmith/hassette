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

from hassette.schemas.app_snapshots import AppFullSnapshot, AppInstanceInfo, AppManifestInfo, AppStatusSnapshot
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
    """Convert a single ``AppInstanceInfo`` to ``AppInstanceResponse``.

    Every response field has a same-named attribute on ``AppInstanceInfo``, so
    ``from_attributes`` copies them directly. The source's extra ``error``
    attribute is ignored.
    """
    return AppInstanceResponse.model_validate(info, from_attributes=True)


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


def app_manifest_response_from(m: AppManifestInfo) -> AppManifestResponse:
    """Convert an ``AppManifestInfo`` snapshot to ``AppManifestResponse``."""
    instances = [instance_response_from(inst) for inst in m.instances]
    return AppManifestResponse(
        app_key=m.app_key,
        class_name=m.class_name,
        display_name=m.display_name,
        filename=m.filename,
        enabled=m.enabled,
        auto_loaded=m.auto_loaded,
        autostart=m.autostart,
        status=cast("ManifestStatus", m.status),  # AppManifestInfo.status is str
        block_reason=m.block_reason,
        instance_count=m.instance_count,
        instances=instances,
        error_message=m.error_message,
        error_traceback=m.error_traceback,
    )


def app_manifest_list_response_from(full: AppFullSnapshot) -> AppManifestListResponse:
    """Convert an ``AppFullSnapshot`` to ``AppManifestListResponse``."""
    return AppManifestListResponse(
        total=full.total,
        running=full.running,
        failed=full.failed,
        stopped=full.stopped,
        disabled=full.disabled,
        blocked=full.blocked,
        manifests=[app_manifest_response_from(m) for m in full.manifests],
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
    # Every ListenerSummary field has a same-named field on ListenerWithSummary, so
    # from_attributes copies them 1:1. The five fields below have no source attribute
    # (they are computed or sourced from live_counts) and are set via model_copy.
    return ListenerWithSummary.model_validate(ls, from_attributes=True).model_copy(
        update={
            "listener_kind": listener_kind_from_topic(ls.topic),
            "handler_summary": format_handler_summary(ls),
            "suppressed_count": suppressed,
            "dropped_count": dropped,
            "backpressure_dropped_count": backpressure_dropped,
        }
    )
