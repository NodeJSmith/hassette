"""Mapping functions from core domain objects to web response models.

Each function converts a domain type (from ``hassette.schemas``) to the
appropriate Pydantic response model from ``hassette_wire``. Web routes
call these instead of receiving pre-mapped response objects from
``RuntimeQueryService`` — except where a service already builds a wire
response model directly, with no domain source to convert (e.g.
``LivenessResponse``, and ``SystemStatusResponse`` from
``RuntimeQueryService.get_system_status()``, returned as-is by
``/health``).

Enum coercion note
------------------
``AppInstanceInfo.status`` is a ``ResourceStatus`` enum (``StrEnum``), and
``AppManifestInfo.status`` is a ``ManifestStatus`` enum (``StrEnum``). Pydantic coerces both
directly — pass the enum value as-is.
"""

from typing import Any

from hassette_wire import (
    AppInstanceResponse,
    AppManifestListResponse,
    AppManifestResponse,
    AppStatusResponse,
    ConnectedPayload,
    ListenerKind,
    ListenerWithSummary,
    ReadinessResponse,
    SystemStatusResponse,
)

from hassette.schemas.app_snapshots import AppFullSnapshot, AppInstanceInfo, AppManifestInfo, AppStatusSnapshot
from hassette.schemas.listener_models import ListenerSummary
from hassette.schemas.live_counts import LiveCounts
from hassette.types.enums import Topic
from hassette.web.telemetry_helpers import format_handler_summary

TOPIC_KIND_MAP: dict[str, ListenerKind] = {
    Topic.HASS_EVENT_STATE_CHANGED: "state change",
    Topic.HASS_EVENT_CALL_SERVICE: "service call",
}


def instance_response_from(info: AppInstanceInfo) -> AppInstanceResponse:
    """Convert a single ``AppInstanceInfo`` to ``AppInstanceResponse``.

    Every response field has a same-named attribute on ``AppInstanceInfo``, so
    ``from_attributes`` copies them directly. The source's extra ``error``
    attribute is ignored.
    """
    return AppInstanceResponse.model_validate(info, from_attributes=True)


def app_status_response_from(snapshot: AppStatusSnapshot) -> AppStatusResponse:
    """Convert an ``AppStatusSnapshot`` to ``AppStatusResponse``."""
    apps = [instance_response_from(info) for info in snapshot.instances]
    return AppStatusResponse(
        total=snapshot.total_count,
        running=snapshot.running_count,
        failed=snapshot.failed_count,
        apps=apps,
        only_apps=snapshot.only_apps,
    )


def manifest_response_fields(manifest: AppManifestInfo) -> dict[str, Any]:
    """Common ``AppManifestInfo`` -> response fields shared by ``AppManifestResponse`` and
    ``DashboardAppGridEntry``.

    Both response models mirror this exact field set from the manifest snapshot. Extracted so
    the two call sites (here and ``dashboard_app_grid``) can't drift apart as the fields evolve.
    """
    # dup-ignore-start: API-response layer output. Shares field names with
    # hassette.core.telemetry.insert_params.manifest_insert_params() (DB-params layer, asserted
    # against verbatim by tests/unit/core/test_manifest_repository.py) by coincidence — same
    # source model, different consumer/field subset; coupling the two layers to satisfy the
    # checker would be the wrong direction.
    return {
        "app_key": manifest.app_key,
        "class_name": manifest.class_name,
        "display_name": manifest.display_name,
        "filename": manifest.filename,
        "enabled": manifest.enabled,
        "auto_loaded": manifest.auto_loaded,
        "autostart": manifest.autostart,
        "status": manifest.status,
        "block_reason": manifest.block_reason,
        "instance_count": manifest.instance_count,
        "instances": [instance_response_from(inst) for inst in manifest.instances],
        "error_message": manifest.error_message,
        "error_traceback": manifest.error_traceback,
        "in_current_config": manifest.in_current_config,
    }
    # dup-ignore-end


def app_manifest_response_from(manifest: AppManifestInfo, recent_invocations_1h: int = 0) -> AppManifestResponse:
    """Convert an ``AppManifestInfo`` snapshot to ``AppManifestResponse``.

    ``recent_invocations_1h`` is not part of the manifest snapshot itself — it comes from a
    separate, independently-degrading telemetry query (see ``.claude/rules/web-api.md``'s
    Category C) — so it's accepted here rather than read off ``manifest``, defaulting to 0 when
    the caller has no count for this app.
    """
    return AppManifestResponse(**manifest_response_fields(manifest), recent_invocations_1h=recent_invocations_1h)


def app_manifest_list_response_from(
    full: AppFullSnapshot, invocations_by_key: dict[str, int] | None = None
) -> AppManifestListResponse:
    """Convert an ``AppFullSnapshot`` to ``AppManifestListResponse``.

    ``invocations_by_key`` maps ``app_key`` to its ``recent_invocations_1h`` count; an app absent
    from the mapping (including when the mapping itself is omitted) defaults to 0.
    """
    invocations_by_key = invocations_by_key or {}
    return AppManifestListResponse(
        total=full.total,
        status_counts=full.status_counts,
        manifests=[
            app_manifest_response_from(manifest, invocations_by_key.get(manifest.app_key, 0))
            for manifest in full.manifests
        ],
        only_apps=full.only_apps,
    )


def readiness_response_from(status: SystemStatusResponse) -> ReadinessResponse:
    """Convert a ``SystemStatusResponse`` to ``ReadinessResponse``.

    Readiness is derived solely from the aggregate status: ready only when ``ok``.
    """
    return ReadinessResponse(status=status.status, ready=status.status == "ok")


def connected_payload_from(status: SystemStatusResponse) -> ConnectedPayload:
    """Build a ``ConnectedPayload`` from a ``SystemStatusResponse``.

    ``uptime_seconds`` is sourced from ``SystemStatusResponse.uptime_seconds``, which
    is computed from the same ``_start_time`` used by ``GET /health``.
    """
    return ConnectedPayload(
        uptime_seconds=status.uptime_seconds,
        entity_count=status.entity_count,
        app_count=status.app_count,
        version=status.version,
    )


def listener_kind_from_topic(topic: str) -> ListenerKind:
    for prefix, kind in TOPIC_KIND_MAP.items():
        if topic.startswith(prefix):
            return kind
    return "event"


def event_name_from_topic(topic: str) -> str:
    """Derive a display name for an event-type listener from its topic.

    Every internal topic follows a ``<namespace>.event.<name>`` shape (see ``Topic``), so the
    last dot-separated segment is the event name (e.g. ``service_status`` from
    ``hassette.event.service_status``). A topic with no dots is returned unchanged.
    """
    return topic.rsplit(".", 1)[-1]


def to_listener_with_summary(
    listener: ListenerSummary,
    live_counts: dict[int, LiveCounts] | None = None,
) -> ListenerWithSummary:
    """Convert a ``ListenerSummary`` to a ``ListenerWithSummary`` response model.

    Copies every field from the summary and appends a computed
    ``handler_summary`` string via :func:`~hassette.web.telemetry_helpers.format_handler_summary`.
    ``target`` is also computed: it is the summary's ``entity_id`` for state/attribute listeners,
    or (since ``entity_id`` is ``None`` for event listeners) falls back to
    :func:`event_name_from_topic`.

    Args:
        listener: The persisted listener summary from the telemetry DB.
        live_counts: Live execution counts keyed by listener ``db_id``, sourced from the bus's
            in-memory guards. A listener with no live guard (e.g. retired) defaults to
            ``LiveCounts(0, 0, 0)``.
    """
    suppressed, dropped, backpressure_dropped = (live_counts or {}).get(listener.listener_id, LiveCounts(0, 0, 0))
    # Every ListenerSummary field has a same-named field on ListenerWithSummary, so splatting
    # model_dump() copies them 1:1. The six fields below have no source attribute (they are
    # computed or sourced from live_counts) and are passed as explicit keyword arguments, so
    # pyright checks their types and the constructor validates every field — a bad value raises.
    return ListenerWithSummary(
        **listener.model_dump(),
        listener_kind=listener_kind_from_topic(listener.topic),
        handler_summary=format_handler_summary(listener),
        target=listener.entity_id or event_name_from_topic(listener.topic),
        suppressed_count=suppressed,
        dropped_count=dropped,
        backpressure_dropped_count=backpressure_dropped,
    )
