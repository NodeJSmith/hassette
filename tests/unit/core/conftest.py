"""Shared fixtures and constants for tests/unit/core/.

Fixture definitions live in family-scoped modules alongside this file
(``_fixtures_*.py``) and are re-exported here so pytest's fixture discovery
and every ``from .conftest import ...`` in this directory's test files keep
working unchanged. See tests/unit/core/CLAUDE.md for the fixture inventory.
"""

from ._fixtures_app_lifecycle import (
    app_handler,
    app_handler_mock_hassette,
    lifecycle_service,
    make_mock_app_instance,
    mock_app_instance,
    mock_factory,
    mock_hassette,
    mock_manifest,
    mock_registry,
    set_registry_apps,
)
from ._fixtures_blocking_io import make_blocking_io_hassette, make_marker_executor
from ._fixtures_bus_scheduler import make_bus_service, make_scheduler_service
from ._fixtures_command_executor import (
    init_executor,
    make_execute_job_cmd,
    make_executor,
    make_invocation,
    make_mock_cmd_listener,
)
from ._fixtures_service_watcher import DummyService, TempService, make_watcher, make_watcher_hassette
from ._fixtures_telemetry import (
    ONCE_LISTENER_NAME,
    TELEMETRY_TEST_DDL,
    assert_listener_count,
    fetch_listener_field,
    insert_committed_execution,
    insert_new_session,
    telemetry_db,
    telemetry_repo,
    telemetry_session_id,
)

__all__ = [
    "ONCE_LISTENER_NAME",
    "TELEMETRY_TEST_DDL",
    "DummyService",
    "TempService",
    "app_handler",
    "app_handler_mock_hassette",
    "assert_listener_count",
    "fetch_listener_field",
    "init_executor",
    "insert_committed_execution",
    "insert_new_session",
    "lifecycle_service",
    "make_blocking_io_hassette",
    "make_bus_service",
    "make_execute_job_cmd",
    "make_executor",
    "make_invocation",
    "make_marker_executor",
    "make_mock_app_instance",
    "make_mock_cmd_listener",
    "make_scheduler_service",
    "make_watcher",
    "make_watcher_hassette",
    "mock_app_instance",
    "mock_factory",
    "mock_hassette",
    "mock_manifest",
    "mock_registry",
    "set_registry_apps",
    "telemetry_db",
    "telemetry_repo",
    "telemetry_session_id",
]
