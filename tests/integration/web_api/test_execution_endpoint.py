"""Integration tests for GET /api/executions/{execution_id}."""

import time
import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import uuid_utils

from hassette.exceptions import TelemetryUnavailableError

from .conftest import make_log_record

if TYPE_CHECKING:
    from httpx import AsyncClient


def make_uuidv7_str(timestamp_s: float) -> str:
    """Construct a UUIDv7 string with an embedded timestamp for testing retention logic."""
    timestamp_ms = int(timestamp_s * 1000)
    # UUIDv7 layout: 48-bit ms timestamp in top 48 bits, version=7, variant=0b10
    # Bits: [48 ms][4 ver=7][12 rand_a][2 var=0b10][62 rand_b]
    rand_a = 0xABC
    rand_b = 0x123456789ABCDE
    version = 7
    variant = 0b10
    high = (timestamp_ms << 16) | (version << 12) | rand_a
    low = (variant << 62) | rand_b
    uuid_int = (high << 64) | low
    return str(uuid.UUID(int=uuid_int))


class TestGetExecutionLogs:
    async def test_happy_path_returns_200_with_records(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Happy path: returns 200 with log records for a valid UUIDv7 execution."""
        execution_id = str(uuid_utils.uuid7())
        records = [make_log_record(1, "INFO", "started", execution_id=execution_id)]
        mock_hassette.telemetry_query_service.get_log_records_by_execution = AsyncMock(return_value=(records, False))

        response = await client.get(f"/api/executions/{execution_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is False
        assert data["retention_expired"] is False
        assert len(data["records"]) == 1
        assert data["records"][0]["execution_id"] == execution_id

    async def test_truncation_when_limit_exceeded(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Returns truncated=True when the service signals truncation."""
        execution_id = str(uuid_utils.uuid7())
        records = [make_log_record(i, execution_id=execution_id) for i in range(500)]
        mock_hassette.telemetry_query_service.get_log_records_by_execution = AsyncMock(return_value=(records, True))

        response = await client.get(f"/api/executions/{execution_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is True
        assert len(data["records"]) == 500

    async def test_uuidv7_old_timestamp_sets_retention_expired(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """UUIDv7 with timestamp older than retention window → retention_expired=True (no DB lookup)."""
        mock_hassette.config.logging.log_retention_days = 3
        old_ts = time.time() - (4 * 86400)  # 4 days ago — beyond 3-day retention
        execution_id = make_uuidv7_str(old_ts)
        mock_hassette.telemetry_query_service.get_log_records_by_execution = AsyncMock(return_value=([], False))
        mock_hassette.telemetry_query_service.check_execution_predates_retention_cutoff = AsyncMock(return_value=False)

        response = await client.get(f"/api/executions/{execution_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["retention_expired"] is True
        assert data["records"] == []
        # UUIDv7 path must NOT call the DB retention check
        mock_hassette.telemetry_query_service.check_execution_predates_retention_cutoff.assert_not_called()

    async def test_uuidv7_recent_timestamp_retention_not_expired(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """UUIDv7 with recent timestamp and empty records → retention_expired=False."""
        mock_hassette.config.logging.log_retention_days = 3
        execution_id = str(uuid_utils.uuid7())  # current timestamp
        mock_hassette.telemetry_query_service.get_log_records_by_execution = AsyncMock(return_value=([], False))

        response = await client.get(f"/api/executions/{execution_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["retention_expired"] is False
        assert data["records"] == []

    async def test_uuidv4_fallback_uses_db_retention_check(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Historical UUIDv4 IDs fall back to the DB retention check."""
        execution_id = str(uuid.uuid4())
        mock_hassette.config.logging.log_retention_days = 3
        mock_hassette.telemetry_query_service.get_log_records_by_execution = AsyncMock(return_value=([], False))
        mock_hassette.telemetry_query_service.check_execution_predates_retention_cutoff = AsyncMock(return_value=True)

        response = await client.get(f"/api/executions/{execution_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["retention_expired"] is True
        mock_hassette.telemetry_query_service.check_execution_predates_retention_cutoff.assert_called_once()

    async def test_uuidv4_fallback_not_expired(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """UUIDv4 ID with DB returning False → retention_expired=False."""
        execution_id = str(uuid.uuid4())
        mock_hassette.config.logging.log_retention_days = 3
        mock_hassette.telemetry_query_service.get_log_records_by_execution = AsyncMock(return_value=([], False))
        mock_hassette.telemetry_query_service.check_execution_predates_retention_cutoff = AsyncMock(return_value=False)

        response = await client.get(f"/api/executions/{execution_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["retention_expired"] is False

    async def test_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """TelemetryUnavailableError → 503 with empty response."""
        execution_id = str(uuid_utils.uuid7())
        mock_hassette.telemetry_query_service.get_log_records_by_execution = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )

        response = await client.get(f"/api/executions/{execution_id}")

        assert response.status_code == 503
        data = response.json()
        assert data["records"] == []
        assert data["truncated"] is False
        assert data["retention_expired"] is False

    async def test_invalid_uuid_returns_422(self, client: "AsyncClient") -> None:
        """Non-UUID execution_id → 422."""
        response = await client.get("/api/executions/not-a-uuid")
        assert response.status_code == 422

    async def test_limit_parameter_is_forwarded(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """The limit query parameter is forwarded to the service call."""
        execution_id = str(uuid_utils.uuid7())
        mock_hassette.config.logging.log_retention_days = 3
        mock_hassette.telemetry_query_service.get_log_records_by_execution = AsyncMock(return_value=([], False))

        response = await client.get(f"/api/executions/{execution_id}?limit=100")

        assert response.status_code == 200
        _, kwargs = mock_hassette.telemetry_query_service.get_log_records_by_execution.call_args
        assert kwargs["limit"] == 100


class TestOldExecutionPathRemoved:
    async def test_old_by_execution_path_returns_404(self, client: "AsyncClient") -> None:
        """GET /api/logs/by-execution/{id} no longer exists — returns 404."""
        response = await client.get("/api/logs/by-execution/some-execution-id")
        assert response.status_code == 404

    async def test_new_executions_path_in_openapi(self, client: "AsyncClient") -> None:
        """GET /api/executions/{execution_id} is present in the OpenAPI spec."""
        response = await client.get("/api/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        paths = spec.get("paths", {})
        assert "/api/executions/{execution_id}" in paths, (
            f"new executions path missing from OpenAPI spec; got: {list(paths)}"
        )

    async def test_old_by_execution_path_absent_from_openapi(self, client: "AsyncClient") -> None:
        """GET /api/logs/by-execution/{execution_id} must not appear in the OpenAPI spec."""
        response = await client.get("/api/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        paths = spec.get("paths", {})
        assert "/api/logs/by-execution/{execution_id}" not in paths, (
            "old by-execution path must not appear in OpenAPI spec after removal"
        )
