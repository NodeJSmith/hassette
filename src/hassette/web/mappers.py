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
``AppManifestInfo.status`` is an ``AppStatus`` enum (``StrEnum``). Pydantic coerces both
directly — pass the enum value as-is.
"""

from hassette_wire import (
    AppInstanceResponse,
    AppListResponse,
    AppSummary,
    ConnectedPayload,
    ListenerKind,
    ListenerWithSummary,
    ReadinessResponse,
    SystemStatusResponse,
)

from hassette.schemas.app_snapshots import AppFullSnapshot, AppInstanceInfo, AppManifestInfo
from hassette.schemas.listener_models import ListenerSummaryRow
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


def app_summary_from(manifest: AppManifestInfo) -> AppSummary:
    """Convert an ``AppManifestInfo`` snapshot to ``AppSummary``."""
    # dup-ignore-start: API-response layer output. Shares field names with
    # hassette.core.telemetry.insert_params.manifest_insert_params() (DB-params layer, asserted
    # against verbatim by tests/unit/core/test_manifest_repository.py) by coincidence — same
    # source model, different consumer/field subset; coupling the two layers to satisfy the
    # checker would be the wrong direction.
    return AppSummary(
        app_key=manifest.app_key,
        class_name=manifest.class_name,
        display_name=manifest.display_name,
        filename=manifest.filename,
        enabled=manifest.enabled,
        auto_loaded=manifest.auto_loaded,
        autostart=manifest.autostart,
        status=manifest.status,
        block_reason=manifest.block_reason,
        instance_count=manifest.instance_count,
        instances=[instance_response_from(inst) for inst in manifest.instances],
        error_message=manifest.error_message,
        error_traceback=manifest.error_traceback,
        in_current_config=manifest.in_current_config,
    )
    # dup-ignore-end


def app_list_response_from(full: AppFullSnapshot) -> AppListResponse:
    """Convert an ``AppFullSnapshot`` to ``AppListResponse``."""
    return AppListResponse(
        total=full.total,
        # Not dict(full.status_counts): dict keys are invariant, so pyright rejects dict[AppStatus, int]
        # here. Building from items() (tuples are covariant) lets the key type widen to OpenAppStatus.
        status_counts=dict(full.status_counts.items()),
        apps=[app_summary_from(manifest) for manifest in full.manifests],
        only_apps=list(full.only_apps),
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
    listener: ListenerSummaryRow,
    live_counts: dict[int, LiveCounts] | None = None,
) -> ListenerWithSummary:
    """Convert a ``ListenerSummaryRow`` to a ``ListenerWithSummary`` response model.

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
    # Every ListenerSummaryRow field has a same-named field on ListenerWithSummary, so splatting
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
