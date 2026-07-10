"""Unit tests for per-service restart_spec class attribute declarations.

Each of the 9 production Service subclasses must declare restart_spec
directly in cls.__dict__ (not inherited) with values matching the design doc.
"""

import pytest

from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.core.web_api_service import WebApiService
from hassette.core.web_ui_watcher import WebUiWatcherService
from hassette.core.websocket_service import WebsocketService
from hassette.resources.restart import RestartSpec
from hassette.types.enums import RestartType

ALL_SERVICES = [
    BusService,
    SchedulerService,
    SyncExecutorService,
    WebsocketService,
    DatabaseService,
    WebApiService,
    CommandExecutor,
    FileWatcherService,
    WebUiWatcherService,
]


class TestAllServicesDeclareRestartSpec:
    @pytest.mark.parametrize("svc_cls", ALL_SERVICES, ids=lambda c: c.__name__)
    def test_all_services_declare_restart_spec(self, svc_cls: type) -> None:
        """Each service must own restart_spec — not just inherit it."""
        assert "restart_spec" in svc_cls.__dict__, (
            f"{svc_cls.__name__} does not declare restart_spec directly in its class body"
        )
        assert isinstance(svc_cls.restart_spec, RestartSpec), (
            f"{svc_cls.__name__}.restart_spec is not a RestartSpec instance"
        )


class TestRestartTypes:
    @pytest.mark.parametrize(
        ("svc_cls", "expected_type"),
        [
            (SyncExecutorService, RestartType.PERMANENT),
            (BusService, RestartType.PERMANENT),
            (SchedulerService, RestartType.PERMANENT),
            (WebsocketService, RestartType.TRANSIENT),
            (DatabaseService, RestartType.TRANSIENT),
            (WebApiService, RestartType.TRANSIENT),
            (CommandExecutor, RestartType.TRANSIENT),
            (FileWatcherService, RestartType.TEMPORARY),
            (WebUiWatcherService, RestartType.TEMPORARY),
        ],
        ids=lambda c: c.__name__ if isinstance(c, type) else str(c),
    )
    def test_restart_type(self, svc_cls: type, expected_type: RestartType) -> None:
        assert svc_cls.restart_spec.restart_type is expected_type


class TestBudgetValues:
    @pytest.mark.parametrize(
        ("svc_cls", "intensity", "period", "startup_timeout"),
        [
            (BusService, 2, 30, None),
            (SchedulerService, 2, 30, None),
            (SyncExecutorService, 2, 30, None),
            (WebsocketService, 5, 300, 60),
            (DatabaseService, 3, 120, None),
            (WebApiService, 3, 60, None),
            (CommandExecutor, 3, 120, None),
            (FileWatcherService, 3, 60, None),
            (WebUiWatcherService, 3, 60, None),
        ],
        ids=lambda c: c.__name__ if isinstance(c, type) else str(c),
    )
    def test_budget(self, svc_cls: type, intensity: int, period: int, startup_timeout: int | None) -> None:
        assert svc_cls.restart_spec.budget_intensity == intensity
        assert svc_cls.restart_spec.budget_period_seconds == period
        if startup_timeout is not None:
            assert svc_cls.restart_spec.startup_timeout_seconds == startup_timeout


class TestDatabaseServiceFatalErrors:
    def test_database_service_fatal_errors(self) -> None:
        """SchemaVersionError must be in DatabaseService.restart_spec.fatal_error_names."""
        assert "SchemaVersionError" in DatabaseService.restart_spec.fatal_error_names

    def test_database_service_no_other_fatal_errors(self) -> None:
        """DatabaseService.restart_spec.fatal_error_names contains only SchemaVersionError."""
        assert DatabaseService.restart_spec.fatal_error_names == ("SchemaVersionError",)


class TestWebsocketServiceNoInternalRetryErrors:
    def test_websocket_no_non_retryable_errors(self) -> None:
        """WebsocketService must not list any non_retryable_error_names.

        InvalidAuthError is a FatalError subclass handled by the CRASHED path —
        it must NOT appear in non_retryable_error_names or fatal_error_names.
        """
        assert WebsocketService.restart_spec.non_retryable_error_names == ()

    def test_websocket_no_fatal_errors(self) -> None:
        """WebsocketService must not list any fatal_error_names."""
        assert WebsocketService.restart_spec.fatal_error_names == ()
