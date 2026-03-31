"""Unit tests for web/mappers.py — domain-to-response model conversions."""

from hassette.core.app_registry import AppFullSnapshot, AppInstanceInfo, AppManifestInfo, AppStatusSnapshot
from hassette.core.domain_models import SystemStatus
from hassette.types.enums import ResourceStatus
from hassette.web.mappers import (
    app_manifest_list_response_from,
    app_status_response_from,
    connected_payload_from,
    system_status_response_from,
)
from hassette.web.models import AppManifestListResponse, AppStatusResponse, ConnectedPayload, SystemStatusResponse

# ---------------------------------------------------------------------------
# app_status_response_from
# ---------------------------------------------------------------------------


def _make_instance(app_key: str, index: int, status: ResourceStatus) -> AppInstanceInfo:
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
        _make_instance("app_a", 0, ResourceStatus.RUNNING),
        _make_instance("app_b", 0, ResourceStatus.RUNNING),
    ]
    failed = [
        _make_instance("app_c", 0, ResourceStatus.FAILED),
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
    running = [_make_instance("app_a", 0, ResourceStatus.RUNNING)]
    snapshot = AppStatusSnapshot(running=running)

    result = app_status_response_from(snapshot)

    assert result.apps[0].status == "running"
    assert isinstance(result.apps[0].status, str)


# ---------------------------------------------------------------------------
# app_manifest_list_response_from
# ---------------------------------------------------------------------------


def _make_manifest(app_key: str, status: str, instances: list[AppInstanceInfo] | None = None) -> AppManifestInfo:
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
    inst0 = _make_instance("app_a", 0, ResourceStatus.RUNNING)
    inst1 = _make_instance("app_a", 1, ResourceStatus.RUNNING)
    manifest = _make_manifest("app_a", "running", instances=[inst0, inst1])
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
    inst = _make_instance("app_a", 0, ResourceStatus.RUNNING)
    manifest = _make_manifest("app_a", "running", instances=[inst])
    full = AppFullSnapshot(manifests=[manifest], total=1, running=1)

    result = app_manifest_list_response_from(full)

    assert result.manifests[0].instances[0].status == "running"
    assert isinstance(result.manifests[0].instances[0].status, str)


def test_app_manifest_list_response_from_manifest_status_already_str():
    """AppManifestInfo.status is already str — verify it passes through without error."""
    manifest = _make_manifest("app_a", "stopped")
    full = AppFullSnapshot(manifests=[manifest], total=1, stopped=1)

    result = app_manifest_list_response_from(full)

    assert result.manifests[0].status == "stopped"


def test_app_manifest_list_response_from_preserves_counts():
    """Aggregate counts from AppFullSnapshot pass through."""
    manifests = [
        _make_manifest("app_a", "running"),
        _make_manifest("app_b", "failed"),
        _make_manifest("app_c", "stopped"),
        _make_manifest("app_d", "disabled"),
        _make_manifest("app_e", "blocked"),
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


# ---------------------------------------------------------------------------
# system_status_response_from
# ---------------------------------------------------------------------------


def _make_system_status(**overrides) -> SystemStatus:
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
    domain = _make_system_status()

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
    domain = _make_system_status(uptime_seconds=0.0)

    result = system_status_response_from(domain)

    assert result.uptime_seconds == 0.0


def test_system_status_response_from_degraded_status():
    """'degraded' status passes through."""
    domain = _make_system_status(status="degraded")

    result = system_status_response_from(domain)

    assert result.status == "degraded"


def test_system_status_response_from_empty_services():
    """Empty services_running list passes through."""
    domain = _make_system_status(services_running=[])

    result = system_status_response_from(domain)

    assert result.services_running == []


# ---------------------------------------------------------------------------
# connected_payload_from
# ---------------------------------------------------------------------------


def test_connected_payload_from_uses_system_status_fields():
    """entity_count and app_count from SystemStatus, session_id from parameter."""
    domain = _make_system_status(entity_count=100, app_count=5)

    result = connected_payload_from(domain, session_id=42)

    assert isinstance(result, ConnectedPayload)
    assert result.entity_count == 100
    assert result.app_count == 5
    assert result.session_id == 42


def test_connected_payload_from_none_session_id():
    """session_id=None passes through."""
    domain = _make_system_status()

    result = connected_payload_from(domain, session_id=None)

    assert result.session_id is None


def test_connected_payload_from_session_id_is_separate_parameter():
    """session_id is not part of SystemStatus — must come from parameter."""
    domain = _make_system_status()
    # Verify SystemStatus has no session_id attribute
    assert not hasattr(domain, "session_id")

    result = connected_payload_from(domain, session_id=99)

    assert result.session_id == 99
