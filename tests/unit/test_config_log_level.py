"""Tests for config_log_level convention compliance.

Verifies each Resource subclass listed in OVERRIDE_CASES:
1. Overrides config_log_level (no fallthrough to global default)
2. Returns the expected config field value
3. Has a LOG_LEVEL_TYPE return annotation

The list is curated, not auto-discovered. When adding a new Resource
subclass, add it to OVERRIDE_CASES. Hassette (root) is an intentional
exception — it uses the base-class global default.
"""

import inspect

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
from hassette.test_utils import make_mock_hassette
from hassette.types.types import LOG_LEVEL_TYPE

LOG_LEVEL_OVERRIDES = {
    "log_level": "INFO",
    "database_service": "DEBUG",
    "bus_service": "WARNING",
    "scheduler_service": "ERROR",
    "app_handler": "CRITICAL",
    "web_api": "DEBUG",
    "websocket": "WARNING",
    "service_watcher": "ERROR",
    "file_watcher": "CRITICAL",
    "task_bucket": "DEBUG",
    "command_executor": "WARNING",
    "apps": "ERROR",
    "state_proxy": "CRITICAL",
    "api": "DEBUG",
}


def _stub_resource(cls: type[Resource]) -> Resource:
    """Create a Resource instance by calling Resource.__init__ only (skips subclass constructors)."""
    hassette = make_mock_hassette(
        sealed=False,
        logging=LOG_LEVEL_OVERRIDES,
        lifecycle={"resource_shutdown_timeout_seconds": 5, "task_cancellation_timeout_seconds": 5},
    )
    obj = cls.__new__(cls)
    Resource.__init__(obj, hassette, parent=hassette)
    return obj


# ---------------------------------------------------------------------------
# All config_log_level override cases
# ---------------------------------------------------------------------------

OVERRIDE_CASES = [
    # Dedicated field overrides (Hassette-registered services)
    # Each tuple: (ResourceClass, nested_attr_on_config_logging)
    (DatabaseService, "database_service"),
    (BusService, "bus_service"),
    (SchedulerService, "scheduler_service"),
    (AppHandler, "app_handler"),
    (WebApiService, "web_api"),
    (WebsocketService, "websocket"),
    (ServiceWatcher, "service_watcher"),
    (FileWatcherService, "file_watcher"),
    (TaskBucket, "task_bucket"),
    (CommandExecutor, "command_executor"),
    (StateProxy, "state_proxy"),
    (Api, "api"),
    (ApiResource, "api"),
    # Cross-bound overrides (child/helper resources)
    (AppLifecycleService, "app_handler"),
    (RuntimeQueryService, "web_api"),
    (TelemetryQueryService, "web_api"),
    (SessionManager, "database_service"),
    (EventStreamService, "bus_service"),
    (WebUiWatcherService, "file_watcher"),
    (StateManager, "state_proxy"),
    (_ScheduledJobQueue, "scheduler_service"),
    # App-owned resources (currently cross-bind to service-level, see #462)
    (Bus, "bus_service"),
    (Scheduler, "scheduler_service"),
    (ApiSyncFacade, "api"),
]


@pytest.mark.parametrize(
    ("cls", "logging_attr"),
    OVERRIDE_CASES,
    ids=[c.__name__ for c, _ in OVERRIDE_CASES],
)
def test_config_log_level_returns_expected_field(cls: type[Resource], logging_attr: str) -> None:
    """Each Resource's config_log_level returns the correct config.logging.* field value."""
    resource = _stub_resource(cls)
    expected = getattr(resource.hassette.config.logging, logging_attr)
    assert resource.config_log_level == expected


# ---------------------------------------------------------------------------
# No-op override regression: Api and ApiResource must NOT return global log_level
# ---------------------------------------------------------------------------


def test_api_does_not_return_global_log_level() -> None:
    """Api.config_log_level returns logging.api, not the global logging.log_level."""
    resource = _stub_resource(Api)
    resource.hassette.config.logging.log_level = "INFO"
    resource.hassette.config.logging.api = "DEBUG"
    assert resource.config_log_level == "DEBUG"
    assert resource.config_log_level != resource.hassette.config.logging.log_level


def test_api_resource_does_not_return_global_log_level() -> None:
    """ApiResource.config_log_level returns logging.api, not the global logging.log_level."""
    resource = _stub_resource(ApiResource)
    resource.hassette.config.logging.log_level = "INFO"
    resource.hassette.config.logging.api = "DEBUG"
    assert resource.config_log_level == "DEBUG"
    assert resource.config_log_level != resource.hassette.config.logging.log_level


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
