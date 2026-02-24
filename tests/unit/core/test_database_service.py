"""Unit tests for DatabaseService."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.database_service import DatabaseService


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    """Create a mock Hassette with database config defaults."""
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
def service(mock_hassette: MagicMock) -> DatabaseService:
    """Create a DatabaseService instance using the factory."""
    return DatabaseService.create(mock_hassette)


def test_create_sets_defaults(service: DatabaseService) -> None:
    """Factory sets _db, _session_id, _db_path, failure counter, and session error flag to initial values."""
    assert service._db is None
    assert service._session_id is None
    assert service._db_path == Path()
    assert service._consecutive_heartbeat_failures == 0
    assert service._session_error is False


def test_config_log_level_delegates_to_config(service: DatabaseService) -> None:
    """config_log_level returns the value from hassette config."""
    service.hassette.config.database_service_log_level = "DEBUG"
    assert service.config_log_level == "DEBUG"


def test_db_property_raises_when_uninitialized(service: DatabaseService) -> None:
    """Accessing db before initialization raises RuntimeError."""
    with pytest.raises(RuntimeError, match="Database connection is not initialized"):
        _ = service.db


def test_session_id_property_raises_when_uninitialized(service: DatabaseService) -> None:
    """Accessing session_id before initialization raises RuntimeError."""
    with pytest.raises(RuntimeError, match="Session ID is not initialized"):
        _ = service.session_id


def test_resolve_db_path_uses_config_when_set(service: DatabaseService) -> None:
    """When db_path is configured, use it directly."""
    service.hassette.config.db_path = Path("/custom/path/my.db")
    result = service._resolve_db_path()
    assert result == Path("/custom/path/my.db").resolve()


def test_resolve_db_path_defaults_to_data_dir(service: DatabaseService, tmp_path: Path) -> None:
    """When db_path is None, default to data_dir / hassette.db."""
    service.hassette.config.db_path = None
    service.hassette.config.data_dir = tmp_path
    result = service._resolve_db_path()
    assert result == tmp_path / "hassette.db"
