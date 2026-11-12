"""Integration tests for the log query and log-level endpoints."""

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import uuid_utils

from hassette.core.migration_runner import run_migrations
from hassette.core.telemetry.summary_queries import LOG_RECORD_SELECT
from hassette.logging_ import LogPersistenceHandler
from tests.support.log_factories import make_log_record as make_stdlib_log_record
from tests.support.sql import sqlite_conn

from .conftest import get_json, make_log_record

if TYPE_CHECKING:
    from httpx2 import AsyncClient

LOGS_RECENT_PATH = "/api/logs/recent"
LOGS_LEVEL_PATH = "/api/logs/level"


class TestLogsEndpoints:
    @pytest.fixture
    def sample_records(self) -> list[dict]:
        """Six log records matching the old buffer fixture, now as DB dicts."""
        return [
            make_log_record(1, "INFO", "Core started", app_key=None),
            make_log_record(2, "INFO", "MyApp initialized", app_key="my_app"),
            make_log_record(3, "WARNING", "Light unresponsive", app_key="my_app"),
            make_log_record(4, "DEBUG", "Heartbeat sent", app_key=None),
            make_log_record(5, "ERROR", "Service call failed", app_key="my_app"),
            make_log_record(6, "INFO", "OtherApp ready", app_key="other_app"),
        ]

    async def test_get_logs_recent_returns_list(
        self, client: "AsyncClient", mock_hassette: MagicMock, sample_records: list[dict]
    ) -> None:
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=sample_records)
        response = await client.get(LOGS_RECENT_PATH)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 6

    async def test_get_logs_recent_preserves_newest_first_order(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        records = [
            make_log_record(4, "INFO", "newest", app_key="my_app"),
            make_log_record(3, "INFO", "same-timestamp-higher-seq", app_key="my_app"),
            make_log_record(2, "INFO", "same-timestamp-lower-seq", app_key="my_app"),
            make_log_record(1, "INFO", "oldest", app_key="my_app"),
        ]
        records[1]["timestamp"] = 2.0
        records[2]["timestamp"] = 2.0
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=records)

        response = await client.get(LOGS_RECENT_PATH)

        assert response.status_code == 200
        assert [entry["message"] for entry in response.json()] == [
            "newest",
            "same-timestamp-higher-seq",
            "same-timestamp-lower-seq",
            "oldest",
        ]

    async def test_get_logs_recent_new_fields_present(
        self, client: "AsyncClient", mock_hassette: MagicMock, sample_records: list[dict]
    ) -> None:
        """New fields (execution_id, instance_name, author) are in the response."""
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=sample_records[:1])
        response = await client.get(LOGS_RECENT_PATH)
        assert response.status_code == 200
        entry = response.json()[0]
        assert "execution_id" in entry
        assert "instance_name" in entry
        assert "author" in entry

    async def test_get_logs_recent_accepts_execution_id_param(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=[])
        response = await client.get(f"{LOGS_RECENT_PATH}?execution_id=abc-123")
        assert response.status_code == 200

    @pytest.mark.parametrize("author", ["app", "framework", "all"])
    async def test_get_logs_recent_accepts_author_param(
        self, client: "AsyncClient", mock_hassette: MagicMock, author: str
    ) -> None:
        forwarded = await get_recent_logs_forwarded_kwargs(client, mock_hassette, f"?author={author}")
        assert forwarded["author"] == author

    async def test_get_logs_recent_omitted_author_requests_the_default_view(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        forwarded = await get_recent_logs_forwarded_kwargs(client, mock_hassette)
        assert forwarded["author"] is None

    async def test_get_logs_recent_ignores_source_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """``source_tier`` is not a log filter any more; unknown query params are ignored, so it filters nothing."""
        forwarded = await get_recent_logs_forwarded_kwargs(client, mock_hassette, "?source_tier=framework")
        assert "source_tier" not in forwarded
        assert forwarded["author"] is None

    async def test_get_logs_recent_forwards_instance_name(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        forwarded = await get_recent_logs_forwarded_kwargs(client, mock_hassette, "?app_key=x&instance_name=instance_1")
        assert forwarded["instance_name"] == "instance_1"

    async def test_get_logs_recent_rejects_instance_name_without_app_key(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """The route keeps requiring ``app_key`` with an instance filter, rather than ignoring it."""
        response = await client.get("/api/logs/recent?instance_name=instance_1")
        assert response.status_code == 422
        assert response.json()["code"] == "validation_failed"
        mock_hassette.telemetry_query_service.get_log_records.assert_not_called()

    async def test_get_logs_recent_defaults_to_all_instances(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        forwarded = await get_recent_logs_forwarded_kwargs(client, mock_hassette, "?app_key=x")
        assert forwarded["instance_name"] is None

    async def test_put_log_level_valid(self, client: "AsyncClient") -> None:
        response = await client.put(LOGS_LEVEL_PATH, json={"logger": "hassette.test", "level": "DEBUG"})
        assert response.status_code == 200
        data = response.json()
        assert data["logger"] == "hassette.test"
        assert data["effective_level"] == "DEBUG"

    async def test_put_log_level_invalid_level(self, client: "AsyncClient") -> None:
        response = await client.put(LOGS_LEVEL_PATH, json={"logger": "hassette.test", "level": "VERBOSE"})
        assert response.status_code == 422

    async def test_put_log_level_changes_take_effect(self, client: "AsyncClient") -> None:
        """Setting DEBUG then INFO changes the effective level each time."""
        await client.put(LOGS_LEVEL_PATH, json={"logger": "hassette.rqs.test.lvl", "level": "DEBUG"})
        assert logging.getLogger("hassette.rqs.test.lvl").level == logging.DEBUG

        r2 = await client.put(LOGS_LEVEL_PATH, json={"logger": "hassette.rqs.test.lvl", "level": "INFO"})
        assert r2.status_code == 200
        assert logging.getLogger("hassette.rqs.test.lvl").level == logging.INFO


class TestCustomLevelRecords:
    """A record logged at a custom level reads back from both routes that serve stored log rows."""

    async def assert_routes_return_level(
        self, client: "AsyncClient", mock_hassette: MagicMock, row: dict[str, Any], expected: str
    ) -> None:
        telemetry = mock_hassette.telemetry_query_service
        telemetry.get_log_records = AsyncMock(return_value=[row])
        telemetry.get_log_records_by_execution = AsyncMock(return_value=([row], False))

        recent = await get_json(client, LOGS_RECENT_PATH)
        execution = await get_json(client, f"/api/executions/{uuid_utils.uuid7()}")

        assert recent[0]["level"] == expected
        assert execution["logs"][0]["level"] == expected

    async def test_captured_record(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        record = make_stdlib_log_record(level=25)
        record.levelname = "SUCCESS"
        handler = LogPersistenceHandler(db_service=MagicMock(), loop=MagicMock())
        row = {**handler.record_to_dict(record), "id": 1}

        await self.assert_routes_return_level(client, mock_hassette, row, "INFO")

    async def test_row_stored_before_the_migration(
        self, client: "AsyncClient", mock_hassette: MagicMock, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "test.db"
        run_migrations(db_path, target=18)
        with sqlite_conn(db_path) as conn:
            conn.execute(
                "INSERT INTO log_records (seq, timestamp, level, logger_name, message, author) "
                "VALUES (1, 0.0, 'TRACE', 'x', 'line', 'app')"
            )
            conn.commit()
        run_migrations(db_path)
        with sqlite_conn(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = dict(conn.execute(LOG_RECORD_SELECT).fetchone())

        await self.assert_routes_return_level(client, mock_hassette, row, "INFO")


async def get_recent_logs_forwarded_kwargs(
    client: "AsyncClient", mock_hassette: MagicMock, query: str = ""
) -> dict[str, Any]:
    """GET /logs/recent with ``query`` and return the kwargs the route forwarded to ``get_log_records``."""
    get_log_records = AsyncMock(return_value=[])
    mock_hassette.telemetry_query_service.get_log_records = get_log_records
    response = await client.get(f"{LOGS_RECENT_PATH}{query}")
    assert response.status_code == 200
    assert get_log_records.await_args is not None
    return dict(get_log_records.await_args.kwargs)
