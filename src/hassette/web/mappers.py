"""Mapping functions from core domain objects to wire models.

Each function converts a domain type (from ``hassette.schemas``) to the
appropriate Pydantic wire model from ``hassette_wire``. Web routes
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
    AppActivityStats,
    AppInstance,
    AppListResponse,
    AppReloadResult,
    AppSummary,
    ConnectedData,
    DeclaredEntity,
    InstanceOutcome,
    LastError,
    LastErrorResult,
    ListenerKind,
    ListenerSummary,
    ReadinessResponse,
    ReloadAllCounts,
    ReloadAllResponse,
    SystemStatusResponse,
)
from whenever import Date, Instant

from hassette.integration.declarations import CommittedEntity
from hassette.schemas.app_outcomes import InstanceOutcome as CoreInstanceOutcome
from hassette.schemas.app_outcomes import OutcomeResult, ReconcileResult, worst_result
from hassette.schemas.app_snapshots import AppFullSnapshot, AppInstanceInfo, AppManifestInfo
from hassette.schemas.execution_models import AppLastError
from hassette.schemas.listener_models import ListenerSummaryRow
from hassette.schemas.live_counts import LiveCounts
from hassette.schemas.summary_models import AppHealthSummary
from hassette.types.enums import Topic
from hassette.web.telemetry_helpers import build_app_health, format_handler_summary

TOPIC_KIND_MAP: dict[str, ListenerKind] = {
    Topic.HASS_EVENT_STATE_CHANGED: "state change",
    Topic.HASS_EVENT_CALL_SERVICE: "service call",
}

#: Live counts for a listener with no live guard (e.g. retired).
NO_LIVE_COUNTS = LiveCounts(0, 0, 0)

CONVERTED_INSTANCE_FIELDS = frozenset({"needs_restart", "entities"})
"""``AppInstance`` fields ``app_instance_from`` converts rather than copies."""


def app_instance_from(instance: AppInstanceInfo) -> AppInstance:
    """Convert a single ``AppInstanceInfo`` to ``AppInstance``.

    Every ``AppInstance`` field has a same-named attribute on ``AppInstanceInfo``. This copies each
    same-named attribute listed in ``AppInstance.model_fields``, except the ones in ``CONVERTED_INSTANCE_FIELDS``:
    ``needs_restart``, whose timestamp is converted by ``NeedsRestartInfo.to_wire``, and ``entities``, converted
    by ``declared_entity_from``. The source's extra ``error`` attribute is ignored.
    """
    fields = {
        name: getattr(instance, name) for name in AppInstance.model_fields if name not in CONVERTED_INSTANCE_FIELDS
    }
    return AppInstance(
        **fields,
        needs_restart=instance.needs_restart.to_wire() if instance.needs_restart else None,
        entities=None if instance.entities is None else [declared_entity_from(entity) for entity in instance.entities],
    )


def declared_entity_from(entity: CommittedEntity) -> DeclaredEntity:
    """Convert a declared entity and its state to ``DeclaredEntity``.

    A timestamp sensor's ``Instant`` becomes its ISO 8601 string with offset and a date sensor's ``Date`` its ISO
    date, the form ``encode_value`` (``hassette.integration.declarations``) stores. Attributes are already a JSON
    object.
    """
    declaration, value = entity.declaration, entity.state.value
    return DeclaredEntity(
        key=declaration.key,
        platform=declaration.platform.value,
        name=declaration.name,
        default_entity_id=declaration.default_entity_id,
        entity_category=declaration.entity_category,
        icon=declaration.icon,
        unit=declaration.unit,
        device_class=declaration.device_class,
        state_class=declaration.state_class,
        options=None if declaration.options is None else list(declaration.options),
        value=value.format_iso() if isinstance(value, Instant | Date) else value,
        attributes=dict(entity.state.attributes),
    )


def instance_outcome_from(outcome: CoreInstanceOutcome) -> InstanceOutcome:
    """Map one app action's per-instance outcome to its wire model."""
    return InstanceOutcome(
        instance_name=outcome.instance_name,
        result=outcome.result.value,
        needs_restart=outcome.needs_restart,
        reason=outcome.reason,
    )


def reload_all_response_from(result: ReconcileResult) -> ReloadAllResponse:
    """Map a reload-all's per-app outcomes to its wire response, apps sorted by key."""
    apps = [
        AppReloadResult(
            app_key=app_key,
            action=app.action.value,
            result=worst_result(app.outcomes).value,
            outcomes=[instance_outcome_from(outcome) for outcome in app.outcomes],
        )
        for app_key, app in sorted(result.apps.items())
    ]
    counts = ReloadAllCounts(
        succeeded=result.count(OutcomeResult.SUCCEEDED),
        failed=result.count(OutcomeResult.FAILED),
        refused=result.count(OutcomeResult.REFUSED),
    )
    return ReloadAllResponse(apps=apps, counts=counts)


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
        description=manifest.description,
        filename=manifest.filename,
        enabled=manifest.enabled,
        autostart=manifest.autostart,
        status=manifest.status,
        status_revision=manifest.status_revision,
        block_reason=manifest.block_reason,
        instance_count=manifest.instance_count,
        instances=[app_instance_from(inst) for inst in manifest.instances],
        error_message=manifest.error_message,
        error_traceback=manifest.error_traceback,
        in_current_config=manifest.in_current_config,
        needs_restart_count=manifest.needs_restart_count,
    )
    # dup-ignore-end


def app_list_response_from(full: AppFullSnapshot, *, boot_id: str, entity_revision: int) -> AppListResponse:
    """Convert an ``AppFullSnapshot`` to ``AppListResponse``, with the entity revision its instances were read at."""
    return AppListResponse(
        total=full.total,
        # Not dict(full.status_counts): dict keys are invariant, so pyright rejects dict[AppStatus, int]
        # here. Building from items() (tuples are covariant) lets the key type widen to OpenAppStatus.
        status_counts=dict(full.status_counts.items()),
        apps=[app_summary_from(manifest) for manifest in full.manifests],
        only_apps=list(full.only_apps),
        boot_id=boot_id,
        entity_revision=entity_revision,
    )


def readiness_response_from(status: SystemStatusResponse) -> ReadinessResponse:
    """Convert a ``SystemStatusResponse`` to ``ReadinessResponse``.

    Readiness is derived solely from the aggregate status: ready only when ``ok``.
    """
    return ReadinessResponse(status=status.status, ready=status.status == "ok")


def connected_data_from(status: SystemStatusResponse) -> ConnectedData:
    """Build a ``ConnectedData`` from a ``SystemStatusResponse``.

    ``uptime_seconds`` is sourced from ``SystemStatusResponse.uptime_seconds``, which
    is computed from the same ``_start_time`` used by ``GET /health``.
    """
    return ConnectedData(
        uptime_seconds=status.uptime_seconds,
        entity_count=status.entity_count,
        app_count=status.app_count,
        version=status.version,
    )


def listener_kind_from_topic(topic: str) -> ListenerKind:
    """Classify a listener by its topic's prefix in ``TOPIC_KIND_MAP``, falling back to ``"event"``."""
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


def listener_summary_from(
    row: ListenerSummaryRow,
    live_counts: dict[int, LiveCounts] | None = None,
) -> ListenerSummary:
    """Convert a ``ListenerSummaryRow`` to a ``ListenerSummary`` wire model.

    Copies every field from the summary and appends a computed
    ``handler_summary`` string via :func:`~hassette.web.telemetry_helpers.format_handler_summary`.
    ``target`` is also computed: it is the summary's ``entity_id`` for state/attribute listeners,
    or (since ``entity_id`` is ``None`` for event listeners) falls back to
    :func:`event_name_from_topic`.

    Args:
        row: The persisted listener summary from the telemetry DB.
        live_counts: Live execution counts keyed by listener ``db_id``, sourced from the bus's
            in-memory guards. A listener with no live guard (e.g. retired) defaults to
            ``NO_LIVE_COUNTS``.
    """
    suppressed, dropped, backpressure_dropped = (live_counts or {}).get(row.listener_id, NO_LIVE_COUNTS)
    # Every ListenerSummaryRow field has a same-named field on ListenerSummary, so splatting
    # model_dump() copies them 1:1. The six fields below have no source attribute (they are
    # computed or sourced from live_counts) and are passed as explicit keyword arguments, so
    # pyright checks their types and the constructor validates every field — a bad value raises.
    return ListenerSummary(
        **row.model_dump(),
        listener_kind=listener_kind_from_topic(row.topic),
        handler_summary=format_handler_summary(row),
        target=row.entity_id or event_name_from_topic(row.topic),
        suppressed_count=suppressed,
        dropped_count=dropped,
        backpressure_dropped_count=backpressure_dropped,
    )


def app_activity_stats_from(summary: AppHealthSummary) -> AppActivityStats:
    """Build an app's ``stats`` part from its health summary."""
    agg = summary.aggregates
    return AppActivityStats(
        handler_count=summary.handler_count,
        job_count=summary.job_count,
        total_invocations=agg.total_invocations,
        total_errors=agg.handler_errors,
        total_timed_out=agg.handler_timed_out,
        total_executions=agg.total_executions,
        total_job_errors=agg.job_errors,
        total_job_timed_out=agg.job_timed_out,
        health=build_app_health(agg),
    )


def last_error_result_from(err: AppLastError | None) -> LastErrorResult:
    """Build an app's ``last_error`` part from a lookup that ran; ``err`` is ``None`` when it found none."""
    if err is None:
        return LastErrorResult(error=None)
    return LastErrorResult(
        error=LastError(error_message=err.error_message, error_type=err.error_type, ts=err.timestamp)
    )
