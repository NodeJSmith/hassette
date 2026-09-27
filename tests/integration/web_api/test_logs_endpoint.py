"""Integration tests for the log query and log-level endpoints."""

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from .conftest import make_log_record, telemetry_error

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
        """New fields (execution_id, instance_name, instance_index, source_tier) are in the response."""
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=sample_records[:1])
        response = await client.get(LOGS_RECENT_PATH)
        assert response.status_code == 200
        entry = response.json()[0]
        assert "execution_id" in entry
        assert "instance_name" in entry
        assert "instance_index" in entry
        assert "source_tier" in entry

    async def test_get_logs_recent_returns_503_on_db_error(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.telemetry_query_service.get_log_records = telemetry_error(message="db error")
        response = await client.get(LOGS_RECENT_PATH)
        assert response.status_code == 503
        assert response.json() == []

    async def test_get_logs_recent_accepts_execution_id_param(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=[])
        response = await client.get(f"{LOGS_RECENT_PATH}?execution_id=abc-123")
        assert response.status_code == 200

    async def test_get_logs_recent_accepts_source_tier_param(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=[])
        response = await client.get(f"{LOGS_RECENT_PATH}?source_tier=app")
        assert response.status_code == 200

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
