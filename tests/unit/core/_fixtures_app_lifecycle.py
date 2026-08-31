"""AppLifecycleService fixtures and mock factories for tests/unit/core/."""

import asyncio
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.core.app_handler import AppHandler
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.types.enums import ResourceStatus

# Shared fixture/factory config values — named so re-tuning is a single-site edit.
APP_STARTUP_TIMEOUT_SECONDS = 30


@pytest.fixture
def mock_hassette() -> AsyncMock:
    """Create a mock Hassette instance with config for AppLifecycleService tests."""
    hassette = make_mock_hassette(
        sealed=False,
        dev_mode=True,
        logging={"app_handler": "DEBUG"},
        lifecycle={"app_startup_timeout_seconds": APP_STARTUP_TIMEOUT_SECONDS},
    )
    hassette.send_event = AsyncMock()
    hassette.command_executor = MagicMock()
    hassette.command_executor.reconcile_registrations = AsyncMock()
    hassette.bus_service = MagicMock()
    hassette.bus_service.router = MagicMock()
    hassette.bus_service.router.get_listeners_by_owner = Mock(return_value=[])
    hassette.scheduler_service = MagicMock()
    hassette.session_id = 1
    hassette.try_session_id.return_value = 1
    return hassette


@pytest.fixture
def app_handler_mock_hassette() -> AsyncMock:
    """Create a mock Hassette instance for AppHandler construction/facade tests.

    Distinct from `mock_hassette` above (which is tuned for `AppLifecycleService` tests) --
    shared by test_app_handler_facade.py and test_app_handler_readiness.py, which both need
    an `AppHandler` built against a mock Hassette rather than a real `AppLifecycleService`.
    """
    hassette = make_mock_hassette(
        sealed=False,
        dev_mode=False,
        logging={"log_level": "DEBUG"},
        lifecycle={"app_startup_timeout_seconds": APP_STARTUP_TIMEOUT_SECONDS},
    )
    hassette.send_event = AsyncMock()
    hassette.bus_service.router = MagicMock()
    hassette.session_id = 1
    hassette.try_session_id.return_value = 1
    return hassette


@pytest.fixture
def app_handler(app_handler_mock_hassette: MagicMock) -> AppHandler:
    with (
        patch("hassette.core.app_lifecycle_service.AppFactory"),
        patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
    ):
        handler = AppHandler(app_handler_mock_hassette)
    return handler


def set_registry_apps(registry: MagicMock, apps: dict[str, dict[int, Any]]) -> None:
    """Configure a mock AppRegistry's app-lookup methods from an apps-shaped dict.

    Mirrors the real AppRegistry's `__contains__`, `app_keys()`, and
    `get_running_apps()` behavior so lifecycle-service code exercising those
    methods sees consistent state.
    """
    registry.__contains__ = Mock(side_effect=lambda key: key in apps)
    registry.app_keys = Mock(side_effect=lambda: list(apps.keys()))
    registry.get_running_apps = Mock(side_effect=lambda key: apps.get(key, {}).copy())
    registry.get = Mock(side_effect=lambda key, index=0: apps.get(key, {}).get(index))


@pytest.fixture
def mock_registry() -> MagicMock:
    """Create a mock AppRegistry instance."""
    registry = MagicMock()
    registry.record_failure = Mock()
    registry.all_apps = Mock(return_value=[])
    registry.clear_all = Mock()
    registry.get_manifest = Mock(return_value=None)
    registry.register_app = Mock()
    registry.unregister_app = Mock(return_value=None)
    registry.set_manifests = Mock()
    registry.set_only_apps = Mock()
    set_registry_apps(registry, {})
    registry.manifests = {}
    registry.enabled_manifests = {}
    registry.active_manifests = {}
    registry.autostart_manifests = {}
    registry.only_apps = frozenset()
    registry.get_snapshot = Mock()
    registry.get_failed_instance_infos = Mock(return_value={})
    registry.prune_stale_failed_indices = Mock(return_value={})
    registry.block_app = Mock()
    registry.unblock_apps = Mock(return_value=set())
    return registry


@pytest.fixture
def mock_factory() -> MagicMock:
    """Create a mock AppFactory."""
    factory = MagicMock()
    factory.create_instances = Mock()
    return factory


@pytest.fixture
def mock_manifest() -> MagicMock:
    """Create a mock AppManifest instance."""
    manifest = MagicMock()
    manifest.class_name = "TestApp"
    manifest.app_key = "test_app"
    manifest.full_path = Path("/apps/test_app.py")
    manifest.display_name = "Test App"
    manifest.enabled = True
    return manifest


def make_mock_app_instance(*, instance_name: str = "test_instance", class_name: str = "MockApp") -> AsyncMock:
    """Create a mock App instance with bus/scheduler stubs."""
    app = AsyncMock()
    app.app_config = MagicMock(instance_name=instance_name)
    app.status = ResourceStatus.NOT_STARTED
    app.class_name = class_name
    app.initialize = AsyncMock()
    app.shutdown = AsyncMock()
    app.ready_event = asyncio.Event()
    app.logger = Mock()
    app.bus = MagicMock()
    app.bus.get_listeners = Mock(return_value=[])
    app.bus.owner_id = f"{class_name}.{instance_name}"
    app.scheduler = MagicMock()
    app.scheduler.get_job_db_ids = Mock(return_value=[])
    app.scheduler.remove_all_jobs = Mock(side_effect=lambda: asyncio.sleep(0))
    return app


@pytest.fixture
def mock_app_instance() -> AsyncMock:
    return make_mock_app_instance()


@pytest.fixture
def lifecycle_service(
    mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
) -> AppLifecycleService:
    """Create an AppLifecycleService with mocked dependencies."""
    logging.getLogger("hassette").propagate = True

    with (
        patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
        patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
    ):
        service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
    service.factory = mock_factory
    return service
