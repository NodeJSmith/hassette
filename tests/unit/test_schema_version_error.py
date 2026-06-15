"""Unit tests for SchemaVersionError extraction from DatabaseService.

Validates:
- SchemaVersionError exists as a typed exception in hassette.exceptions
- SchemaVersionError is NOT a FatalError subclass (must reach FAILED path)
- DatabaseService.handle_schema_version raises SchemaVersionError (not RuntimeError)
  when the DB schema version is ahead of the code's expected head
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hassette.core.database_service import DatabaseService
from hassette.exceptions import FatalError, SchemaVersionError


class TestSchemaVersionErrorType:
    def test_schema_version_error_is_not_fatal_error(self) -> None:
        """SchemaVersionError must NOT be a FatalError subclass.

        It is listed in fatal_error_names on DatabaseService.restart_spec,
        which means the watcher matches it by name. It should reach the FAILED
        path (handled), not the CRASHED path (FatalError subclass).
        """
        assert not issubclass(SchemaVersionError, FatalError)

    def test_schema_version_error_is_exception(self) -> None:
        """SchemaVersionError must be a subclass of Exception."""
        assert issubclass(SchemaVersionError, Exception)

    def test_schema_version_error_can_be_instantiated(self) -> None:
        """SchemaVersionError can be raised and caught normally."""
        with pytest.raises(SchemaVersionError):
            raise SchemaVersionError("schema 002 is ahead of expected 001")


class TestDatabaseServiceRaisesSchemaVersionError:
    """Tests that handle_schema_version raises SchemaVersionError when the DB is ahead of the code."""

    def make_svc(self, tmp_path: Path) -> DatabaseService:
        """Build a DatabaseService instance without going through __init__."""
        hassette_mock = MagicMock()
        hassette_mock.config.database.path = None
        hassette_mock.config.data_dir = tmp_path
        hassette_mock.config.logging.database_service = "INFO"

        svc = DatabaseService.__new__(DatabaseService)
        svc._db = None
        svc._read_db = None
        svc._db_path = tmp_path / "test.db"
        svc._consecutive_heartbeat_failures = 0
        svc._consecutive_size_triggers = 0
        svc._db_write_queue = None
        svc._db_worker_task = None
        svc.hassette = hassette_mock
        svc.logger = MagicMock()
        return svc

    def test_schema_version_error_raised_when_db_ahead(self, tmp_path: Path) -> None:
        """When the DB's PRAGMA user_version is ahead of the code's expected head, SchemaVersionError is raised.

        The migration runner uses PRAGMA user_version (integer), not Alembic string revisions.
        get_current_db_version() reads the on-disk integer; get_expected_head_version() returns
        the highest numbered migration file. When current > expected, startup is refused.
        """
        db_path = tmp_path / "test.db"
        db_path.touch()  # file must exist for the check to run

        svc = self.make_svc(tmp_path)

        with (
            patch.object(DatabaseService, "get_current_db_version", return_value=999),
            patch.object(DatabaseService, "get_expected_head_version", return_value=1),
            pytest.raises(SchemaVersionError, match="ahead"),
        ):
            asyncio.run(svc.handle_schema_version(db_path))
