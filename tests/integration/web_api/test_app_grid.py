"""Integration tests for the ``GET /api/telemetry/app-grid`` endpoint."""

import logging
from dataclasses import fields
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from hassette_wire import AppActivity

from hassette.schemas.execution_models import AppLastError
from hassette.schemas.summary_models import AppHealthAggregates, AppHealthSummary
from hassette.web.routes.telemetry import GridEnrichments
from tests.support.web_manifest_helpers import make_manifest_db_row

from .conftest import APP_GRID_PATH, get_json, seed_grid_apps, telemetry_error

if TYPE_CHECKING:
    from httpx2 import AsyncClient

GRID_SINCE = 1_700_000_000.0
GRID_ENRICHMENT_QUERIES = (
    "get_all_app_summaries",
    "get_per_app_activity_buckets",
    "get_per_app_last_errors",
    "get_blocking_event_counts",
)

ROUTE_LOGGER_NAME = "hassette.web.routes.telemetry"
SUMMARY_WARNING_PREFIX = "App grid served without these activity parts: "

# What `seed_grid_enrichments` gives the seeded app, and how each value reads on the wire.
SEEDED_INVOCATIONS = 12
SEEDED_BUCKET = (3, 1)
SEEDED_BUCKET_JSON = {"ok": SEEDED_BUCKET[0], "err": SEEDED_BUCKET[1]}
SEEDED_ERROR_MESSAGE = "boom"
SEEDED_BLOCKING_EVENTS = 9
SEEDED_PARTS = {
    "stats": SEEDED_INVOCATIONS,
    "activity_buckets": [SEEDED_BUCKET_JSON],
    "last_error": SEEDED_ERROR_MESSAGE,
    "blocking_event_count": SEEDED_BLOCKING_EVENTS,
}
"""The seeded app's four parts, reduced to the values the tests compare."""


class TestAppGrid:
    async def test_app_grid_rows_nest_app_and_activity(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """The grid spine is DB-sourced; each row is the app summary plus its activity."""
        seed_grid_apps(mock_hassette, "my_app")

        data = await get_json(client, APP_GRID_PATH)

        assert len(data["apps"]) == 1
        entry = data["apps"][0]
        assert set(entry) == {"app", "activity"}
        assert entry["app"]["app_key"] == "my_app"
        assert entry["app"]["class_name"] == "MyApp"
        assert entry["app"]["filename"] == "my_app.py"
        assert entry["app"]["in_current_config"] is False
        assert "recent_invocations_1h" not in entry["app"]
        # No summary for the app: zero counts and an all-zero health record with no averages.
        assert entry["activity"]["stats"]["total_invocations"] == 0
        assert entry["activity"]["stats"]["health"] == {
            "error_rate": 0.0,
            "error_rate_class": "good",
            "health_status": "excellent",
            "last_activity_ts": None,
            "handler_avg_duration_ms": None,
            "job_avg_duration_ms": None,
        }

    async def test_app_grid_includes_db_only_apps(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """A DB-only app (no matching in-memory manifest) appears in the grid."""
        mock_hassette.telemetry_query_service.get_all_app_manifests = AsyncMock(
            return_value=[
                make_manifest_db_row(
                    app_key="orphan_app",
                    class_name="OrphanApp",
                    display_name="Orphan App",
                    filename="orphan_app.py",
                )
            ]
        )

        data = await get_json(client, APP_GRID_PATH)

        orphan = next(e["app"] for e in data["apps"] if e["app"]["app_key"] == "orphan_app")
        assert orphan["status"] == "stopped"
        assert orphan["in_current_config"] is False
        assert orphan["instance_count"] == 0

    async def test_app_grid_carries_blocking_event_counts(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Each entry gets its app's blocking-event count for the requested window; absent apps read 0."""
        seed_grid_apps(mock_hassette, "my_app", "clean_app")
        mock_hassette.telemetry_query_service.get_blocking_event_counts = AsyncMock(
            return_value={"my_app": SEEDED_BLOCKING_EVENTS}
        )

        data = await get_json(client, f"{APP_GRID_PATH}?since={GRID_SINCE}")

        counts = {e["app"]["app_key"]: e["activity"]["blocking_event_count"] for e in data["apps"]}
        assert counts == {"my_app": SEEDED_BLOCKING_EVENTS, "clean_app": 0}
        call = mock_hassette.telemetry_query_service.get_blocking_event_counts.call_args
        assert call.kwargs == {"since": pytest.approx(GRID_SINCE)}

    async def test_grid_with_since_computes_every_part_and_echoes_since(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """With a window, every part is computed; an app with no error in it reads ``{error: null}``."""
        seed_grid_apps(mock_hassette, "my_app", "quiet_app")
        seed_grid_enrichments(mock_hassette, "my_app")

        data = await get_json(client, f"{APP_GRID_PATH}?since={GRID_SINCE}")

        assert data["since"] == pytest.approx(GRID_SINCE)
        rows = {e["app"]["app_key"]: e["activity"] for e in data["apps"]}
        assert rows["my_app"]["stats"]["total_invocations"] == SEEDED_INVOCATIONS
        assert rows["my_app"]["activity_buckets"] == [SEEDED_BUCKET_JSON]
        assert rows["my_app"]["last_error"] == {
            "error": {
                "error_message": SEEDED_ERROR_MESSAGE,
                "error_type": "ValueError",
                "ts": pytest.approx(GRID_SINCE + 5),
            }
        }
        assert rows["my_app"]["blocking_event_count"] == SEEDED_BLOCKING_EVENTS
        # Ran and found nothing for this app: computed empties, never null.
        assert rows["quiet_app"]["stats"]["total_invocations"] == 0
        assert rows["quiet_app"]["activity_buckets"] == []
        assert rows["quiet_app"]["last_error"] == {"error": None}
        assert rows["quiet_app"]["blocking_event_count"] == 0

    async def test_grid_without_since_leaves_windowed_parts_null(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """since=None means all-time totals: buckets and last error don't run, so they are null."""
        seed_grid_apps(mock_hassette, "my_app")
        seed_grid_enrichments(mock_hassette, "my_app")

        data = await get_json(client, APP_GRID_PATH)

        assert data["since"] is None
        activity = data["apps"][0]["activity"]
        assert activity["activity_buckets"] is None
        assert activity["last_error"] is None
        assert activity["stats"]["total_invocations"] == SEEDED_INVOCATIONS
        assert activity["blocking_event_count"] == SEEDED_BLOCKING_EVENTS
        mock_hassette.telemetry_query_service.get_per_app_activity_buckets.assert_not_called()
        mock_hassette.telemetry_query_service.get_per_app_last_errors.assert_not_called()

    @pytest.mark.parametrize(
        ("query_method", "part"),
        [
            ("get_all_app_summaries", "stats"),
            ("get_per_app_activity_buckets", "activity_buckets"),
            ("get_per_app_last_errors", "last_error"),
            ("get_blocking_event_counts", "blocking_event_count"),
        ],
    )
    async def test_a_failed_enrichment_nulls_only_its_part_in_every_row(
        self,
        client: "AsyncClient",
        mock_hassette: MagicMock,
        caplog: pytest.LogCaptureFixture,
        query_method: str,
        part: str,
    ) -> None:
        """The failed part is null in every row, the other three keep their real values, and the
        route logs one summary warning naming the part (the operator's only aggregate signal).
        """
        seed_grid_apps(mock_hassette, "my_app", "other_app")
        seed_grid_enrichments(mock_hassette, "my_app")
        setattr(mock_hassette.telemetry_query_service, query_method, telemetry_error(f"{query_method} failed"))

        with caplog.at_level(logging.WARNING, logger=ROUTE_LOGGER_NAME):
            data = await get_json(client, f"{APP_GRID_PATH}?since={GRID_SINCE}")

        assert all(e["activity"][part] is None for e in data["apps"])
        my_app_activity = next(e["activity"] for e in data["apps"] if e["app"]["app_key"] == "my_app")
        actual_parts = {
            "stats": my_app_activity["stats"] and my_app_activity["stats"]["total_invocations"],
            "activity_buckets": my_app_activity["activity_buckets"],
            "last_error": my_app_activity["last_error"] and my_app_activity["last_error"]["error"]["error_message"],
            "blocking_event_count": my_app_activity["blocking_event_count"],
        }
        assert actual_parts == {**SEEDED_PARTS, part: None}
        assert grid_summary_warnings(caplog) == [f"{SUMMARY_WARNING_PREFIX}{part}"]
        (record,) = grid_summary_records(caplog)
        assert record.failed_parts == [part]  # pyright: ignore[reportAttributeAccessIssue]
        assert record.since == pytest.approx(GRID_SINCE)  # pyright: ignore[reportAttributeAccessIssue]

    async def test_every_failed_part_is_named_in_one_summary_warning(
        self, client: "AsyncClient", mock_hassette: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        seed_grid_apps(mock_hassette, "my_app")
        for method in GRID_ENRICHMENT_QUERIES:
            setattr(mock_hassette.telemetry_query_service, method, telemetry_error(f"{method} failed"))

        with caplog.at_level(logging.WARNING, logger=ROUTE_LOGGER_NAME):
            data = await get_json(client, f"{APP_GRID_PATH}?since={GRID_SINCE}")

        assert data["apps"][0]["activity"] == {
            "stats": None,
            "activity_buckets": None,
            "last_error": None,
            "blocking_event_count": None,
        }
        assert grid_summary_warnings(caplog) == [
            f"{SUMMARY_WARNING_PREFIX}stats, activity_buckets, last_error, blocking_event_count"
        ]

    async def test_a_fully_successful_grid_logs_no_summary_warning(
        self, client: "AsyncClient", mock_hassette: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        seed_grid_apps(mock_hassette, "my_app")

        with caplog.at_level(logging.WARNING, logger=ROUTE_LOGGER_NAME):
            await get_json(client, f"{APP_GRID_PATH}?since={GRID_SINCE}")

        assert grid_summary_warnings(caplog) == []

    @pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
    @pytest.mark.parametrize("path", [APP_GRID_PATH, "/api/logs/recent"])
    async def test_non_finite_since_is_rejected(self, client: "AsyncClient", path: str, value: str) -> None:
        """A non-finite since would echo as null (all-time) while the windowed queries ran."""
        response = await client.get(f"{path}?since={value}")
        assert response.status_code == 422


def test_grid_enrichments_has_one_field_per_activity_part() -> None:
    """The route names failed parts from these fields, so a new AppActivity part can't skip the warning."""
    assert [f.name for f in fields(GridEnrichments)] == list(AppActivity.model_fields)


def seed_grid_enrichments(mock_hassette: MagicMock, app_key: str) -> None:
    """Give ``app_key`` real, non-zero results from all four grid enrichment queries."""
    ts = mock_hassette.telemetry_query_service
    aggregates = AppHealthAggregates.empty().model_copy(
        update={"total_invocations": SEEDED_INVOCATIONS, "handler_errors": 1}
    )
    ts.get_all_app_summaries = AsyncMock(
        return_value={app_key: AppHealthSummary(handler_count=2, job_count=1, aggregates=aggregates)}
    )
    ts.get_per_app_activity_buckets = AsyncMock(return_value={app_key: [SEEDED_BUCKET]})
    ts.get_per_app_last_errors = AsyncMock(
        return_value={
            app_key: AppLastError(error_message=SEEDED_ERROR_MESSAGE, error_type="ValueError", timestamp=GRID_SINCE + 5)
        }
    )
    ts.get_blocking_event_counts = AsyncMock(return_value={app_key: SEEDED_BLOCKING_EVENTS})


def grid_summary_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage().startswith(SUMMARY_WARNING_PREFIX)]


def grid_summary_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in grid_summary_records(caplog)]
