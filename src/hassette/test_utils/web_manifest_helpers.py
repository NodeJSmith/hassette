"""Reusable factory functions for app manifest and snapshot test data.

These build manifest and snapshot objects used by both e2e and integration web tests.
"""

from collections.abc import Sequence
from typing import Any

from hassette.schemas.app_snapshots import AppFullSnapshot, AppInstanceInfo, AppManifestInfo, tally_manifest_statuses
from hassette.test_utils.config import DEFAULT_TEST_APP_KEY, TEST_ISO_TIMESTAMP
from hassette.types.enums import ManifestStatus, ResourceStatus
from hassette.web.models import (
    AppInstanceResponse,
    AppManifestListResponse,
    AppManifestResponse,
)


def _tally_statuses(manifests: Sequence[AppManifestInfo | AppManifestResponse]) -> dict[str, int]:
    """Count manifests by status.

    Delegates to ``tally_manifest_statuses()`` (schemas.app_snapshots), which only needs
    ``.status`` on each item — safe for ``AppManifestResponse`` too despite the narrower
    ``Iterable[AppManifestInfo]`` type hint.
    """
    return tally_manifest_statuses(manifests)  # pyright: ignore[reportArgumentType]


def make_app_instance_info(
    app_key: str = DEFAULT_TEST_APP_KEY,
    index: int = 0,
    instance_name: str | None = None,
    class_name: str = "MyApp",
    status: ResourceStatus = ResourceStatus.RUNNING,
    error: Exception | None = None,
    error_message: str | None = None,
    error_traceback: str | None = None,
    owner_id: str | None = None,
) -> AppInstanceInfo:
    """Build an AppInstanceInfo with sensible defaults.

    ``instance_name`` defaults to ``"{class_name}[{index}]"`` — the shape ``AppRegistry`` itself
    produces — so callers only pass it when a test asserts on a different one.
    """
    return AppInstanceInfo(
        app_key=app_key,
        index=index,
        instance_name=instance_name if instance_name is not None else f"{class_name}[{index}]",
        class_name=class_name,
        status=status,
        error=error,
        error_message=error_message,
        error_traceback=error_traceback,
        owner_id=owner_id,
    )


def make_full_snapshot(
    manifests: list[AppManifestInfo] | None = None,
    only_apps: list[str] | None = None,
) -> AppFullSnapshot:
    """Build an AppFullSnapshot from a list of manifests."""
    manifests = manifests or []
    counts = _tally_statuses(manifests)
    return AppFullSnapshot(
        manifests=manifests,
        only_apps=only_apps or [],
        total=len(manifests),
        status_counts=counts,
    )


def make_manifest(
    app_key: str = DEFAULT_TEST_APP_KEY,
    class_name: str = "TestApp",
    display_name: str = "Test App",
    filename: str = "test_app.py",
    enabled: bool = True,
    auto_loaded: bool = False,
    status: ManifestStatus = ManifestStatus.RUNNING,
    block_reason: str | None = None,
    instance_count: int = 1,
    instances: list[AppInstanceInfo] | None = None,
    error_message: str | None = None,
    error_traceback: str | None = None,
    autostart: bool = True,
    in_current_config: bool = True,
) -> AppManifestInfo:
    """Build an AppManifestInfo with sensible defaults."""
    return AppManifestInfo(
        app_key=app_key,
        class_name=class_name,
        display_name=display_name,
        filename=filename,
        enabled=enabled,
        auto_loaded=auto_loaded,
        status=status,
        block_reason=block_reason,
        instance_count=instance_count,
        instances=instances or [],
        error_message=error_message,
        error_traceback=error_traceback,
        autostart=autostart,
        in_current_config=in_current_config,
    )


def make_manifest_response(
    app_key: str = DEFAULT_TEST_APP_KEY,
    class_name: str = "TestApp",
    display_name: str = "Test App",
    filename: str = "test_app.py",
    enabled: bool = True,
    auto_loaded: bool = False,
    status: ManifestStatus = ManifestStatus.RUNNING,
    instance_count: int = 1,
    instances: list[AppInstanceResponse] | None = None,
    in_current_config: bool = True,
) -> AppManifestResponse:
    """Build an AppManifestResponse with sensible defaults."""
    return AppManifestResponse(
        app_key=app_key,
        class_name=class_name,
        display_name=display_name,
        filename=filename,
        enabled=enabled,
        auto_loaded=auto_loaded,
        status=status,
        instance_count=instance_count,
        instances=instances or [],
        in_current_config=in_current_config,
    )


def make_manifest_db_row(app_key: str = DEFAULT_TEST_APP_KEY, **overrides: Any) -> dict[str, Any]:
    """Build a plain dict shaped like a row from ``get_all_app_manifests()``/``get_app_manifest()``.

    Mocks the telemetry query service's raw DB-row return shape (10 fields) in web-layer
    integration tests. Distinct from ``make_manifest()``, which builds the post-overlay
    ``AppManifestInfo`` dataclass.
    """
    row: dict[str, Any] = {
        "id": 1,
        "app_key": app_key,
        "class_name": "MyApp",
        "display_name": "My App",
        "filename": "my_app.py",
        "enabled": 1,
        "autostart": 1,
        "auto_loaded": 0,
        "created_at": TEST_ISO_TIMESTAMP,
        "updated_at": TEST_ISO_TIMESTAMP,
    }
    row.update(overrides)
    return row


def make_manifest_list_response(
    manifests: list[AppManifestResponse] | None = None,
) -> AppManifestListResponse:
    """Build an AppManifestListResponse from a list of manifests."""
    manifests = manifests or []
    counts = _tally_statuses(manifests)
    return AppManifestListResponse(
        manifests=manifests,
        total=len(manifests),
        status_counts=counts,
    )
