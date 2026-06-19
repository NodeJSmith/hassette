"""Unit tests for web/mappers.py — domain-to-response model conversions."""

from hassette.core.app_registry import AppFullSnapshot, AppInstanceInfo, AppManifestInfo, AppStatusSnapshot
from hassette.core.bus_service import LiveCounts
from hassette.core.domain_models import SystemStatus
from hassette.core.telemetry_models import ListenerSummary
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.types.enums import ResourceStatus
from hassette.web.mappers import (
    app_manifest_list_response_from,
    app_status_response_from,
    connected_payload_from,
    readiness_response_from,
    system_status_response_from,
    to_listener_with_summary,
)
from hassette.web.models import (
    AppManifestListResponse,
    AppStatusResponse,
    ConnectedPayload,
    LivenessResponse,
    ReadinessResponse,
    SystemStatusResponse,
)


def make_instance(app_key: str, index: int, status: ResourceStatus) -> AppInstanceInfo:
    return AppInstanceInfo(
        app_key=app_key,
        index=index,
        instance_name=f"{app_key}.{index}",
        class_name="MyApp",
        status=status,
    )


def test_app_status_response_from_merges_running_and_failed():
    """Snapshot with 2 running + 1 failed produces response with 3 apps."""
    running = [
        make_instance("app_a", 0, ResourceStatus.RUNNING),
        make_instance("app_b", 0, ResourceStatus.RUNNING),
    ]
    failed = [
        make_instance("app_c", 0, ResourceStatus.FAILED),
    ]
    snapshot = AppStatusSnapshot(running=running, failed=failed)

    result = app_status_response_from(snapshot)

    assert isinstance(result, AppStatusResponse)
    assert result.total == 3
    assert result.running == 2
    assert result.failed == 1
    assert len(result.apps) == 3
    app_keys = {app.app_key for app in result.apps}
    assert app_keys == {"app_a", "app_b", "app_c"}


def test_app_status_response_from_empty_snapshot():
    """No apps produces empty list."""
    snapshot = AppStatusSnapshot()

    result = app_status_response_from(snapshot)

    assert isinstance(result, AppStatusResponse)
    assert result.total == 0
    assert result.running == 0
    assert result.failed == 0
    assert result.apps == []


def test_app_status_response_from_preserves_only_app():
    """only_app field is propagated from snapshot."""
    snapshot = AppStatusSnapshot(only_app="special_app")

    result = app_status_response_from(snapshot)

    assert result.only_app == "special_app"


def test_app_status_response_from_coerces_resource_status_enum():
    """AppInstanceInfo.status (ResourceStatus enum) → string in response."""
    running = [make_instance("app_a", 0, ResourceStatus.RUNNING)]
    snapshot = AppStatusSnapshot(running=running)

    result = app_status_response_from(snapshot)

    assert result.apps[0].status == "running"
    assert isinstance(result.apps[0].status, str)


def make_manifest(app_key: str, status: str, instances: list[AppInstanceInfo] | None = None) -> AppManifestInfo:
    return AppManifestInfo(
        app_key=app_key,
        class_name="MyApp",
        display_name="My App",
        filename="my_app.py",
        enabled=True,
        auto_loaded=True,
        status=status,
        instances=instances or [],
        instance_count=len(instances) if instances else 0,
    )


def test_app_manifest_list_response_from_builds_nested_instances():
    """Verify nested AppInstanceResponse objects are built correctly."""
    inst0 = make_instance("app_a", 0, ResourceStatus.RUNNING)
    inst1 = make_instance("app_a", 1, ResourceStatus.RUNNING)
    manifest = make_manifest("app_a", "running", instances=[inst0, inst1])
    full = AppFullSnapshot(
        manifests=[manifest],
        total=1,
        running=1,
        failed=0,
        stopped=0,
        disabled=0,
        blocked=0,
    )

    result = app_manifest_list_response_from(full)

    assert isinstance(result, AppManifestListResponse)
    assert len(result.manifests) == 1
    app_manifest_resp = result.manifests[0]
    assert app_manifest_resp.app_key == "app_a"
    assert len(app_manifest_resp.instances) == 2
    assert app_manifest_resp.instances[0].app_key == "app_a"
    assert app_manifest_resp.instances[0].index == 0
    assert app_manifest_resp.instances[1].index == 1


def test_app_manifest_list_response_from_coerces_resource_status_enum():
    """AppInstanceInfo.status (ResourceStatus enum) → string in response."""
    inst = make_instance("app_a", 0, ResourceStatus.RUNNING)
    manifest = make_manifest("app_a", "running", instances=[inst])
    full = AppFullSnapshot(manifests=[manifest], total=1, running=1)

    result = app_manifest_list_response_from(full)

    assert result.manifests[0].instances[0].status == "running"
    assert isinstance(result.manifests[0].instances[0].status, str)


def test_app_manifest_list_response_from_manifest_status_already_str():
    """AppManifestInfo.status is already str — verify it passes through without error."""
    manifest = make_manifest("app_a", "stopped")
    full = AppFullSnapshot(manifests=[manifest], total=1, stopped=1)

    result = app_manifest_list_response_from(full)

    assert result.manifests[0].status == "stopped"


def test_app_manifest_list_response_from_preserves_counts():
    """Aggregate counts from AppFullSnapshot pass through."""
    manifests = [
        make_manifest("app_a", "running"),
        make_manifest("app_b", "failed"),
        make_manifest("app_c", "stopped"),
        make_manifest("app_d", "disabled"),
        make_manifest("app_e", "blocked"),
    ]
    full = AppFullSnapshot(
        manifests=manifests,
        total=5,
        running=1,
        failed=1,
        stopped=1,
        disabled=1,
        blocked=1,
    )

    result = app_manifest_list_response_from(full)

    assert result.total == 5
    assert result.running == 1
    assert result.failed == 1
    assert result.stopped == 1
    assert result.disabled == 1
    assert result.blocked == 1


def make_system_status(**overrides) -> SystemStatus:
    defaults = {
        "status": "ok",
        "websocket_connected": True,
        "uptime_seconds": 123.4,
        "entity_count": 42,
        "app_count": 3,
        "services_running": ["service_a", "service_b"],
    }
    defaults.update(overrides)
    return SystemStatus(**defaults)


def test_system_status_response_from_preserves_all_fields():
    """All 6 fields including services_running are preserved."""
    domain = make_system_status()

    result = system_status_response_from(domain)

    assert isinstance(result, SystemStatusResponse)
    assert result.status == "ok"
    assert result.websocket_connected is True
    assert result.uptime_seconds == 123.4
    assert result.entity_count == 42
    assert result.app_count == 3
    assert result.services_running == ["service_a", "service_b"]


def test_system_status_response_from_uptime_zero():
    """uptime_seconds=0.0 (earliest possible value) passes through."""
    domain = make_system_status(uptime_seconds=0.0)

    result = system_status_response_from(domain)

    assert result.uptime_seconds == 0.0


def test_system_status_response_from_degraded_status():
    """'degraded' status passes through."""
    domain = make_system_status(status="degraded")

    result = system_status_response_from(domain)

    assert result.status == "degraded"


def test_system_status_response_from_empty_services():
    """Empty services_running list passes through."""
    domain = make_system_status(services_running=[])

    result = system_status_response_from(domain)

    assert result.services_running == []


def test_connected_payload_from_uses_system_status_fields():
    """entity_count, app_count, and uptime_seconds come from SystemStatus."""
    domain = make_system_status(entity_count=100, app_count=5, uptime_seconds=300.0)

    result = connected_payload_from(domain)

    assert isinstance(result, ConnectedPayload)
    assert result.entity_count == 100
    assert result.app_count == 5
    assert result.uptime_seconds == 300.0


def test_connected_payload_from_uptime_seconds_from_status():
    """uptime_seconds is derived from SystemStatus, not a separate parameter."""
    domain = make_system_status(uptime_seconds=42.5)

    result = connected_payload_from(domain)

    assert result.uptime_seconds == 42.5


def test_connected_payload_from_no_session_id():
    """ConnectedPayload no longer carries session_id."""
    domain = make_system_status()

    result = connected_payload_from(domain)

    assert not hasattr(result, "session_id")


def make_listener_summary(**overrides) -> ListenerSummary:
    defaults = {
        "listener_id": 1,
        "app_key": "test_app",
        "instance_index": 0,
        "handler_method": "on_event",
        "topic": "hass.event.state_changed",
        "debounce": None,
        "throttle": None,
        "once": 0,
        "priority": 0,
        "predicate_description": None,
        "human_description": None,
        "source_location": TEST_SOURCE_LOCATION,
        "registration_source": None,
        "source_tier": "app",
        "total_invocations": 0,
        "successful": 0,
        "failed": 0,
        "di_failures": 0,
        "cancelled": 0,
        "timed_out": 0,
        "total_duration_ms": 0.0,
        "avg_duration_ms": 0.0,
        "min_duration_ms": None,
        "max_duration_ms": None,
        "last_invoked_at": None,
        "last_error_type": None,
        "last_error_message": None,
        "last_error_traceback": None,
    }
    defaults.update(overrides)
    return ListenerSummary(**defaults)


def test_to_listener_with_summary_passes_through_last_error_traceback():
    """last_error_traceback from ListenerSummary passes through to ListenerWithSummary."""

    traceback_text = "Traceback (most recent call last):\n  File test.py, line 1\nValueError: oops"
    summary = make_listener_summary(
        last_error_type="ValueError",
        last_error_message="oops",
        last_error_traceback=traceback_text,
    )

    result = to_listener_with_summary(summary)

    assert result.last_error_traceback == traceback_text


def test_to_listener_with_summary_none_traceback_when_no_error():
    """last_error_traceback is None when ListenerSummary has no error."""

    summary = make_listener_summary()

    result = to_listener_with_summary(summary)

    assert result.last_error_traceback is None


def test_to_listener_with_summary_mode_passthrough():
    """mode passes through from the DB summary to the response model."""
    summary = make_listener_summary(mode="queued")

    result = to_listener_with_summary(summary)

    assert result.mode == "queued"


def test_to_listener_with_summary_thread_leaked_passthrough():
    """thread_leaked passes through from the DB summary to the response model (#1049 parity).

    Guards the listener-only mapper layer: a field added to ListenerSummary but not copied
    here would be silently 0 in the API.
    """
    summary = make_listener_summary(thread_leaked=4)

    result = to_listener_with_summary(summary)

    assert result.thread_leaked == 4


def test_to_listener_with_summary_merges_live_counts_by_db_id():
    """suppressed/dropped/backpressure_dropped come from the live snapshot keyed by listener db_id."""
    summary = make_listener_summary(listener_id=42)

    result = to_listener_with_summary(summary, {42: LiveCounts(suppressed=3, dropped=5, backpressure_dropped=0)})

    assert result.suppressed_count == 3
    assert result.dropped_count == 5
    assert result.backpressure_dropped_count == 0


def test_to_listener_with_summary_defaults_counts_to_zero_when_no_live_guard():
    """A listener absent from the live snapshot (retired) reports zero counts."""
    summary = make_listener_summary(listener_id=42)

    result = to_listener_with_summary(summary, {99: LiveCounts(suppressed=1, dropped=1, backpressure_dropped=0)})

    assert result.suppressed_count == 0
    assert result.dropped_count == 0
    assert result.backpressure_dropped_count == 0


def test_to_listener_with_summary_backpressure_dropped_flows_into_backpressure_dropped_count():
    """backpressure_dropped > 0 on a live guard flows into backpressure_dropped_count; suppressed/dropped unchanged."""
    summary = make_listener_summary(listener_id=10)

    result = to_listener_with_summary(summary, {10: LiveCounts(suppressed=2, dropped=1, backpressure_dropped=7)})

    assert result.backpressure_dropped_count == 7
    assert result.suppressed_count == 2
    assert result.dropped_count == 1


def test_to_listener_with_summary_backpressure_passthrough():
    """backpressure policy passes through from the DB summary to the response model."""
    summary = make_listener_summary(backpressure="drop_newest")

    result = to_listener_with_summary(summary)

    assert result.backpressure == "drop_newest"


def test_to_listener_with_summary_backpressure_defaults_to_block():
    """backpressure defaults to 'block' when ListenerSummary has no override."""
    summary = make_listener_summary()

    result = to_listener_with_summary(summary)

    assert result.backpressure == "block"


def test_to_listener_with_summary_min_max_none_passthrough():
    """min_duration_ms and max_duration_ms pass through as None (no invocations)."""

    summary = make_listener_summary(min_duration_ms=None, max_duration_ms=None)

    result = to_listener_with_summary(summary)

    assert result.min_duration_ms is None
    assert result.max_duration_ms is None


def test_to_listener_with_summary_min_max_numeric_passthrough():
    """min_duration_ms and max_duration_ms pass through as numeric values."""

    summary = make_listener_summary(min_duration_ms=5.0, max_duration_ms=100.0, total_invocations=3)

    result = to_listener_with_summary(summary)

    assert result.min_duration_ms == 5.0
    assert result.max_duration_ms == 100.0


# LivenessResponse and ReadinessResponse


def test_liveness_response_has_live_status():
    """LivenessResponse.status defaults to 'live'."""
    result = LivenessResponse()
    assert result.status == "live"


def test_liveness_response_status_field_is_literal_live():
    """LivenessResponse constructed with status='live' produces the correct body."""
    result = LivenessResponse(status="live")
    assert result.status == "live"


def test_readiness_response_from_ok_status():
    """readiness_response_from produces ready=True for 'ok' status."""
    domain = make_system_status(status="ok")
    result = readiness_response_from(domain)
    assert isinstance(result, ReadinessResponse)
    assert result.ready is True
    assert result.status == "ok"


def test_readiness_response_from_degraded_status():
    """readiness_response_from produces ready=False for 'degraded' status."""
    domain = make_system_status(status="degraded", websocket_connected=False)
    result = readiness_response_from(domain)
    assert result.ready is False
    assert result.status == "degraded"


def test_readiness_response_from_starting_status():
    """readiness_response_from produces ready=False for 'starting' status."""
    domain = make_system_status(status="starting", websocket_connected=False)
    result = readiness_response_from(domain)
    assert result.ready is False
    assert result.status == "starting"
