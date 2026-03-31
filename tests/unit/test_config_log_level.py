"""Tests for config_log_level convention compliance.

Verifies that every concrete Resource subclass:
1. Overrides config_log_level (no fallthrough to global default)
2. Returns the expected config field value
3. Has a LOG_LEVEL_TYPE return annotation
"""

import inspect
from unittest.mock import MagicMock

import pytest

from hassette.api.api import Api
from hassette.api.sync import ApiSyncFacade
from hassette.app.app import App
from hassette.bus.bus import Bus
from hassette.core.api_resource import ApiResource
from hassette.core.app_handler import AppHandler
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.event_stream_service import EventStreamService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.scheduler_service import SchedulerService, _ScheduledJobQueue
from hassette.core.service_watcher import ServiceWatcher
from hassette.core.session_manager import SessionManager
from hassette.core.state_proxy import StateProxy
from hassette.core.telemetry_query_service import TelemetryQueryService
from hassette.core.web_api_service import WebApiService
from hassette.core.web_ui_watcher import WebUiWatcherService
from hassette.core.websocket_service import WebsocketService
from hassette.resources.base import Resource
from hassette.scheduler.scheduler import Scheduler
from hassette.state_manager.state_manager import StateManager
from hassette.task_bucket.task_bucket import TaskBucket
from hassette.types.types import LOG_LEVEL_TYPE


def _make_mock_hassette() -> MagicMock:
    """Create a minimal mock Hassette with all log level config fields set to distinct values."""
    hassette = MagicMock()
    hassette.config.log_level = "INFO"
    hassette.config.database_service_log_level = "DEBUG"
    hassette.config.bus_service_log_level = "WARNING"
    hassette.config.scheduler_service_log_level = "ERROR"
    hassette.config.app_handler_log_level = "CRITICAL"
    hassette.config.web_api_log_level = "DEBUG"
    hassette.config.websocket_log_level = "WARNING"
    hassette.config.service_watcher_log_level = "ERROR"
    hassette.config.file_watcher_log_level = "CRITICAL"
    hassette.config.task_bucket_log_level = "DEBUG"
    hassette.config.command_executor_log_level = "WARNING"
    hassette.config.apps_log_level = "ERROR"
    hassette.config.state_proxy_log_level = "CRITICAL"
    hassette.config.api_log_level = "DEBUG"
    return hassette


def _stub_resource(cls: type[Resource]) -> Resource:
    """Create a Resource instance by calling Resource.__init__ only (skips subclass constructors).

    This lets us test config_log_level in isolation without wiring up each class's
    specific dependencies (streams, executors, registries, etc.).
    """
    hassette = _make_mock_hassette()
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    obj = cls.__new__(cls)
    Resource.__init__(obj, hassette, parent=hassette)
    return obj


# ---------------------------------------------------------------------------
# All config_log_level override cases
# ---------------------------------------------------------------------------

OVERRIDE_CASES = [
    # Dedicated field overrides (Hassette-registered services)
    (DatabaseService, "database_service_log_level"),
    (BusService, "bus_service_log_level"),
    (SchedulerService, "scheduler_service_log_level"),
    (AppHandler, "app_handler_log_level"),
    (WebApiService, "web_api_log_level"),
    (WebsocketService, "websocket_log_level"),
    (ServiceWatcher, "service_watcher_log_level"),
    (FileWatcherService, "file_watcher_log_level"),
    (TaskBucket, "task_bucket_log_level"),
    (CommandExecutor, "command_executor_log_level"),
    (StateProxy, "state_proxy_log_level"),
    (Api, "api_log_level"),
    (ApiResource, "api_log_level"),
    # Cross-bound overrides (child/helper resources)
    (AppLifecycleService, "app_handler_log_level"),
    (RuntimeQueryService, "web_api_log_level"),
    (TelemetryQueryService, "web_api_log_level"),
    (SessionManager, "database_service_log_level"),
    (EventStreamService, "bus_service_log_level"),
    (WebUiWatcherService, "file_watcher_log_level"),
    (StateManager, "state_proxy_log_level"),
    (_ScheduledJobQueue, "scheduler_service_log_level"),
    # App-owned resources (currently cross-bind to service-level, see #462)
    (Bus, "bus_service_log_level"),
    (Scheduler, "scheduler_service_log_level"),
    (ApiSyncFacade, "api_log_level"),
]


@pytest.mark.parametrize(
    ("cls", "config_field"),
    OVERRIDE_CASES,
    ids=[c.__name__ for c, _ in OVERRIDE_CASES],
)
def test_config_log_level_returns_expected_field(cls: type[Resource], config_field: str) -> None:
    """Each Resource's config_log_level returns the correct config field value."""
    resource = _stub_resource(cls)
    expected = getattr(resource.hassette.config, config_field)
    assert resource.config_log_level == expected


# ---------------------------------------------------------------------------
# No-op override regression: Api and ApiResource must NOT return global log_level
# ---------------------------------------------------------------------------


def test_api_does_not_return_global_log_level() -> None:
    """Api.config_log_level returns api_log_level, not the global log_level."""
    resource = _stub_resource(Api)
    resource.hassette.config.log_level = "INFO"
    resource.hassette.config.api_log_level = "DEBUG"
    assert resource.config_log_level == "DEBUG"
    assert resource.config_log_level != resource.hassette.config.log_level


def test_api_resource_does_not_return_global_log_level() -> None:
    """ApiResource.config_log_level returns api_log_level, not the global log_level."""
    resource = _stub_resource(ApiResource)
    resource.hassette.config.log_level = "INFO"
    resource.hassette.config.api_log_level = "DEBUG"
    assert resource.config_log_level == "DEBUG"
    assert resource.config_log_level != resource.hassette.config.log_level


# ---------------------------------------------------------------------------
# Type annotation introspection
# ---------------------------------------------------------------------------

ALL_OVERRIDE_CLASSES: list[type[Resource]] = [cls for cls, _ in OVERRIDE_CASES] + [App]


@pytest.mark.parametrize("cls", ALL_OVERRIDE_CLASSES, ids=[c.__name__ for c in ALL_OVERRIDE_CLASSES])
def test_config_log_level_has_log_level_type_annotation(cls: type[Resource]) -> None:
    """Every config_log_level override must declare -> LOG_LEVEL_TYPE."""
    prop = inspect.getattr_static(cls, "config_log_level")
    assert isinstance(prop, property), f"{cls.__name__}.config_log_level is not a property"
    hints = {"return": prop.fget.__annotations__.get("return")} if prop.fget else {}
    assert hints.get("return") is LOG_LEVEL_TYPE, (
        f"{cls.__name__}.config_log_level return annotation is {hints.get('return')}, expected LOG_LEVEL_TYPE"
    )
