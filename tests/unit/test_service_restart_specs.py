"""Unit tests for per-service restart_spec class attribute declarations.

Each of the 8 production Service subclasses must declare restart_spec
directly in cls.__dict__ (not inherited) with values matching the design doc.
"""

import pytest

from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.web_api_service import WebApiService
from hassette.core.web_ui_watcher import WebUiWatcherService
from hassette.core.websocket_service import WebsocketService
from hassette.resources.base import RestartSpec
from hassette.types.enums import RestartType

_ALL_SERVICES = [
    BusService,
    SchedulerService,
    WebsocketService,
    DatabaseService,
    WebApiService,
    CommandExecutor,
    FileWatcherService,
    WebUiWatcherService,
]


class TestAllServicesDeclareRestartSpec:
    @pytest.mark.parametrize("svc_cls", _ALL_SERVICES, ids=lambda c: c.__name__)
    def test_all_services_declare_restart_spec(self, svc_cls: type) -> None:
        """Each service must own restart_spec — not just inherit it."""
        assert "restart_spec" in svc_cls.__dict__, (
            f"{svc_cls.__name__} does not declare restart_spec directly in its class body"
        )
        assert isinstance(svc_cls.restart_spec, RestartSpec), (
            f"{svc_cls.__name__}.restart_spec is not a RestartSpec instance"
        )


class TestRestartTypes:
    def test_bus_service_permanent(self) -> None:
        """BusService must use PERMANENT restart type."""
        assert BusService.restart_spec.restart_type is RestartType.PERMANENT

    def test_scheduler_service_permanent(self) -> None:
        """SchedulerService must use PERMANENT restart type."""
        assert SchedulerService.restart_spec.restart_type is RestartType.PERMANENT

    def test_websocket_service_transient(self) -> None:
        """WebsocketService must use TRANSIENT restart type."""
        assert WebsocketService.restart_spec.restart_type is RestartType.TRANSIENT

    def test_database_service_transient(self) -> None:
        """DatabaseService must use TRANSIENT restart type."""
        assert DatabaseService.restart_spec.restart_type is RestartType.TRANSIENT

    def test_web_api_service_transient(self) -> None:
        """WebApiService must use TRANSIENT restart type."""
        assert WebApiService.restart_spec.restart_type is RestartType.TRANSIENT

    def test_command_executor_transient(self) -> None:
        """CommandExecutor must use TRANSIENT restart type."""
        assert CommandExecutor.restart_spec.restart_type is RestartType.TRANSIENT

    def test_file_watcher_temporary(self) -> None:
        """FileWatcherService must use TEMPORARY restart type."""
        assert FileWatcherService.restart_spec.restart_type is RestartType.TEMPORARY

    def test_web_ui_watcher_temporary(self) -> None:
        """WebUiWatcherService must use TEMPORARY restart type."""
        assert WebUiWatcherService.restart_spec.restart_type is RestartType.TEMPORARY


class TestBudgetValues:
    def test_bus_service_budget(self) -> None:
        assert BusService.restart_spec.budget_intensity == 2
        assert BusService.restart_spec.budget_period_seconds == 30

    def test_scheduler_service_budget(self) -> None:
        assert SchedulerService.restart_spec.budget_intensity == 2
        assert SchedulerService.restart_spec.budget_period_seconds == 30

    def test_websocket_service_budget(self) -> None:
        assert WebsocketService.restart_spec.budget_intensity == 5
        assert WebsocketService.restart_spec.budget_period_seconds == 300
        assert WebsocketService.restart_spec.startup_timeout_seconds == 60

    def test_database_service_budget(self) -> None:
        assert DatabaseService.restart_spec.budget_intensity == 3
        assert DatabaseService.restart_spec.budget_period_seconds == 120

    def test_web_api_service_budget(self) -> None:
        assert WebApiService.restart_spec.budget_intensity == 3
        assert WebApiService.restart_spec.budget_period_seconds == 60

    def test_command_executor_budget(self) -> None:
        assert CommandExecutor.restart_spec.budget_intensity == 3
        assert CommandExecutor.restart_spec.budget_period_seconds == 120

    def test_file_watcher_budget(self) -> None:
        assert FileWatcherService.restart_spec.budget_intensity == 3
        assert FileWatcherService.restart_spec.budget_period_seconds == 60

    def test_web_ui_watcher_budget(self) -> None:
        assert WebUiWatcherService.restart_spec.budget_intensity == 3
        assert WebUiWatcherService.restart_spec.budget_period_seconds == 60


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
