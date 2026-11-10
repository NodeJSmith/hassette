"""Integration tests for GET /api/executions/{execution_id}."""

import time
import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
import uuid_utils

from tests.support.web_telemetry_helpers import make_api_write, make_execution

from .conftest import get_json, make_log_record

if TYPE_CHECKING:
    from hassette_wire import ApiWrite, Execution
    from httpx2 import AsyncClient

EXECUTION_PATH = "/api/executions/{execution_id}"


async def get_execution_detail(
    client: "AsyncClient",
    mock_hassette: MagicMock,
    execution_id: str,
    *,
    records: list[dict] | None = None,
    truncated: bool = False,
    writes: "list[ApiWrite] | None" = None,
    writes_truncated: bool = False,
    execution: "Execution | None" = None,
    query: str = "",
) -> dict:
    """Wire the three per-execution queries, then GET the execution detail endpoint.

    Each stub returns the shape its real query does: `(logs, truncated)` and `(writes, truncated)`
    tuples, and the execution or None, so the arrange step mirrors the service contract.
    """
    mock_hassette.telemetry_query_service.get_log_records_by_execution = AsyncMock(
        return_value=(records or [], truncated)
    )
    mock_hassette.telemetry_query_service.get_api_writes_by_execution = AsyncMock(
        return_value=(writes or [], writes_truncated)
    )
    mock_hassette.telemetry_query_service.get_execution_by_id = AsyncMock(return_value=execution)
    mock_hassette.config.logging.log_retention_days = 3  # read whenever there are no log records
    return await get_json(client, EXECUTION_PATH.format(execution_id=execution_id) + query)


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


class TestGetExecutionDetail:
    async def test_happy_path_returns_200_with_records(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Happy path: returns 200 with log records for a valid UUIDv7 execution."""
        execution_id = str(uuid_utils.uuid7())
        records = [make_log_record(1, "INFO", "started", execution_id=execution_id)]

        data = await get_execution_detail(client, mock_hassette, execution_id, records=records)

        assert data["logs_truncated"] is False
        assert data["retention_expired"] is False
        assert len(data["logs"]) == 1
        assert data["logs"][0]["execution_id"] == execution_id

    async def test_truncation_when_limit_exceeded(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Returns logs_truncated=True when the service signals truncation."""
        execution_id = str(uuid_utils.uuid7())
        records = [make_log_record(i, execution_id=execution_id) for i in range(500)]

        data = await get_execution_detail(client, mock_hassette, execution_id, records=records, truncated=True)

        assert data["logs_truncated"] is True
        assert len(data["logs"]) == 500

    async def test_uuidv7_old_timestamp_sets_retention_expired(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """UUIDv7 with timestamp older than retention window → retention_expired=True (no DB lookup)."""
        old_ts = time.time() - (4 * 86400)  # 4 days ago — beyond 3-day retention
        mock_hassette.telemetry_query_service.check_execution_predates_retention_cutoff = AsyncMock(return_value=False)

        data = await get_execution_detail(client, mock_hassette, make_uuidv7_str(old_ts))

        assert data["retention_expired"] is True
        assert data["logs"] == []
        # UUIDv7 path must NOT call the DB retention check
        mock_hassette.telemetry_query_service.check_execution_predates_retention_cutoff.assert_not_called()

    async def test_uuidv7_recent_timestamp_retention_not_expired(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """UUIDv7 with recent timestamp and empty records → retention_expired=False."""
        data = await get_execution_detail(client, mock_hassette, str(uuid_utils.uuid7()))  # current timestamp

        assert data["retention_expired"] is False
        assert data["logs"] == []

    async def test_uuidv4_fallback_uses_db_retention_check(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Historical UUIDv4 IDs fall back to the DB retention check."""
        mock_hassette.telemetry_query_service.check_execution_predates_retention_cutoff = AsyncMock(return_value=True)

        data = await get_execution_detail(client, mock_hassette, str(uuid.uuid4()))

        assert data["retention_expired"] is True
        mock_hassette.telemetry_query_service.check_execution_predates_retention_cutoff.assert_called_once()

    async def test_uuidv4_fallback_not_expired(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """UUIDv4 ID with DB returning False → retention_expired=False."""
        mock_hassette.telemetry_query_service.check_execution_predates_retention_cutoff = AsyncMock(return_value=False)

        data = await get_execution_detail(client, mock_hassette, str(uuid.uuid4()))

        assert data["retention_expired"] is False

    async def test_invalid_uuid_returns_422(self, client: "AsyncClient") -> None:
        """Non-UUID execution_id → 422."""
        response = await client.get("/api/executions/not-a-uuid")
        assert response.status_code == 422

    async def test_limit_parameter_is_forwarded(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """The limit query parameter is forwarded to the service call."""
        await get_execution_detail(client, mock_hassette, str(uuid_utils.uuid7()), query="?limit=100")

        _, kwargs = mock_hassette.telemetry_query_service.get_log_records_by_execution.call_args
        assert kwargs["limit"] == 100
        _, write_kwargs = mock_hassette.telemetry_query_service.get_api_writes_by_execution.call_args
        assert write_kwargs["limit"] == 100

    async def test_api_writes_are_returned(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """The writes the service returns appear in ``api_writes``, untruncated by default."""
        execution_id = str(uuid_utils.uuid7())
        writes = [
            make_api_write("w1", execution_id=execution_id),
            make_api_write("w2", operation="light.turn_off", execution_id=execution_id),
        ]

        data = await get_execution_detail(client, mock_hassette, execution_id, writes=writes)

        assert [(w["write_id"], w["operation"]) for w in data["api_writes"]] == [
            ("w1", "light.turn_on"),
            ("w2", "light.turn_off"),
        ]
        assert data["api_writes_truncated"] is False

    async def test_api_writes_truncated_flag_is_passed_through(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        data = await get_execution_detail(
            client, mock_hassette, str(uuid_utils.uuid7()), writes=[make_api_write()], writes_truncated=True
        )

        assert data["api_writes_truncated"] is True

    async def test_execution_is_null_until_the_record_lands(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        data = await get_execution_detail(client, mock_hassette, str(uuid_utils.uuid7()))

        assert data["execution"] is None

    async def test_execution_is_returned_when_recorded(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        execution_id = str(uuid_utils.uuid7())

        data = await get_execution_detail(
            client, mock_hassette, execution_id, execution=make_execution(execution_id=execution_id)
        )

        assert data["execution"]["execution_id"] == execution_id
        mock_hassette.telemetry_query_service.get_execution_by_id.assert_awaited_once_with(execution_id)

    @pytest.mark.parametrize(("query", "expected"), [("", None), ("?author=all", "all"), ("?author=app", "app")])
    async def test_author_parameter_is_forwarded(
        self, client: "AsyncClient", mock_hassette: MagicMock, query: str, expected: str | None
    ) -> None:
        """``author`` is forwarded as given; omitting it forwards ``None``, which applies the default view."""
        await get_execution_detail(client, mock_hassette, str(uuid_utils.uuid7()), query=query)

        _, kwargs = mock_hassette.telemetry_query_service.get_log_records_by_execution.call_args
        assert kwargs["author"] == expected


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
