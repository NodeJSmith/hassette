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


def logs_since_path(since_id: int) -> str:
    """Build a `/api/logs/since/{since_id}` URL — single source of truth so a route rename
    only needs to change here.
    """
    return f"/api/logs/since/{since_id}"


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

    async def test_get_logs_since_zero_returns_all_records(
        self, client: "AsyncClient", mock_hassette: MagicMock, sample_records: list[dict]
    ) -> None:
        """GET /logs/since/0 returns every record, ordered by id ASC."""
        mock_hassette.telemetry_query_service.get_log_records_since = AsyncMock(return_value=sample_records)
        response = await client.get(logs_since_path(0))
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 6
        assert [entry["id"] for entry in data] == [1, 2, 3, 4, 5, 6]

    async def test_get_logs_since_forwards_since_id_and_returns_only_records_after_cursor(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """GET /logs/since/{N} forwards N and returns only records the service reports as after it."""
        records_after_3 = [
            make_log_record(4, "DEBUG", "Heartbeat sent", app_key=None),
            make_log_record(5, "ERROR", "Service call failed", app_key="my_app"),
            make_log_record(6, "INFO", "OtherApp ready", app_key="other_app"),
        ]
        mock_service = AsyncMock(return_value=records_after_3)
        mock_hassette.telemetry_query_service.get_log_records_since = mock_service

        response = await client.get(logs_since_path(3))

        assert response.status_code == 200
        data = response.json()
        assert [entry["id"] for entry in data] == [4, 5, 6]
        mock_service.assert_awaited_once()
        assert mock_service.await_args.args[0] == 3

    async def test_get_logs_since_composes_app_key_filter_with_cursor(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """GET /logs/since/{N}?app_key=foo forwards both the cursor and the app_key filter."""
        mock_service = AsyncMock(return_value=[])
        mock_hassette.telemetry_query_service.get_log_records_since = mock_service

        response = await client.get(f"{logs_since_path(3)}?app_key=my_app")

        assert response.status_code == 200
        mock_service.assert_awaited_once()
        assert mock_service.await_args.args[0] == 3
        assert mock_service.await_args.kwargs["app_key"] == "my_app"

    async def test_get_logs_since_new_fields_present(
        self, client: "AsyncClient", mock_hassette: MagicMock, sample_records: list[dict]
    ) -> None:
        """New fields (execution_id, instance_name, instance_index, source_tier) are in the response."""
        mock_hassette.telemetry_query_service.get_log_records_since = AsyncMock(return_value=sample_records[:1])
        response = await client.get(logs_since_path(0))
        assert response.status_code == 200
        entry = response.json()[0]
        assert "execution_id" in entry
        assert "instance_name" in entry
        assert "instance_index" in entry
        assert "source_tier" in entry

    async def test_get_logs_since_returns_503_on_db_error(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.telemetry_query_service.get_log_records_since = telemetry_error(message="db error")
        response = await client.get(logs_since_path(0))
        assert response.status_code == 503
        assert response.json() == []

    async def test_get_logs_since_rejects_negative_since_id(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        response = await client.get(logs_since_path(-1))
        assert response.status_code == 422

    async def test_get_logs_since_validates_level(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get(f"{logs_since_path(0)}?level=VERBOSE")
        assert response.status_code == 422

    async def test_get_logs_since_validates_source_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get(f"{logs_since_path(0)}?source_tier=bogus")
        assert response.status_code == 422

    async def test_get_logs_since_limit_at_max_accepted(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """`limit=500` is the shared `LimitQuery` cap for the cursor catch-up endpoint."""
        mock_hassette.telemetry_query_service.get_log_records_since = AsyncMock(return_value=[])
        response = await client.get(f"{logs_since_path(0)}?limit=500")
        assert response.status_code == 200

    async def test_get_logs_since_limit_over_max_rejected(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """`limit=501` exceeds the shared `LimitQuery` cap and is rejected with 422."""
        response = await client.get(f"{logs_since_path(0)}?limit=501")
        assert response.status_code == 422

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
