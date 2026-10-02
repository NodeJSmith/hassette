"""Integration tests for blocking-event read queries against a real migrated database."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from hassette_wire import StackFrame

from hassette.config.classes import AppManifest
from hassette.core.database_service import DatabaseService
from hassette.core.telemetry import blocking_queries
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.schemas.log_models import BlockingEvent

from .helpers import DbFixture, insert_execution, insert_invocation, insert_job, insert_listener

APP_DIR = "/srv/apps"
CALL_SITE = StackFrame(filename=f"{APP_DIR}/helper.py", lineno=98, function="fetch", module="helper")
HANDLER = StackFrame(filename=f"{APP_DIR}/my_app.py", lineno=10, function="on_event", module="my_app")


@pytest.fixture(autouse=True)
def configured_app(db_hassette: MagicMock) -> None:
    """Configure ``my_app`` under APP_DIR so frames there classify as its app code."""
    db_hassette.config.apps.manifests = {
        "my_app": AppManifest.model_validate(
            {
                "app_key": "my_app",
                "filename": "my_app.py",
                "class_name": "MyApp",
                "app_dir": APP_DIR,
                "full_path": f"{APP_DIR}/my_app.py",
            }
        )
    }


async def insert_event(db_svc: DatabaseService, **overrides: Any) -> None:
    fields: dict[str, Any] = {
        "session_id": None,
        "app_key": "my_app",
        "instance_name": None,
        "instance_index": 0,
        "execution_id": None,
        "tier": "watchdog",
        "primitive": None,
        "source_location": None,
        "stall_duration_ms": 200.0,
        "detected_ts": 1000.0,
        "source_tier": "app",
        "reason": "attributed",
        "frames": [CALL_SITE, HANDLER],
    }
    fields.update(overrides)
    if fields["app_key"] is None:
        fields["source_tier"] = "framework"
    await TelemetryRepository(db_svc).insert_blocking_event(BlockingEvent(**fields))


async def tag_execution(db_svc: DatabaseService, execution_row_id: int, execution_id: str) -> None:
    await db_svc.db.execute("UPDATE executions SET execution_id = ? WHERE id = ?", (execution_id, execution_row_id))
    await db_svc.db.commit()


class TestBlockingFindings:
    async def test_groups_by_call_site_and_names_the_handlers(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """Rows from a listener and a job at one call site → one finding naming both, via execution_id."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, app_key="my_app", name="kitchen", handler_method="on_event")
        job_id = await insert_job(db_svc, app_key="my_app", job_name="nightly", handler_method="run_job")
        await tag_execution(db_svc, await insert_invocation(db_svc, listener_id, session_id), "exec-l")
        await tag_execution(db_svc, await insert_execution(db_svc, job_id, session_id), "exec-j")
        await insert_event(db_svc, execution_id="exec-l", detected_ts=2000.0, stall_duration_ms=500.0)
        await insert_event(db_svc, execution_id="exec-j", detected_ts=1000.0)

        result = await query_service.get_blocking_findings(app_key="my_app", instance_index=0, since=None)

        [finding] = result.findings
        assert not result.truncated
        assert finding.call_site is not None
        assert (finding.call_site.display_path, finding.call_site.lineno) == ("helper.py", 98)
        assert [(h.kind, h.id, h.name, h.handler_method) for h in finding.handlers] == [
            ("listener", listener_id, "kitchen", "on_event"),
            ("job", job_id, "nightly", "run_job"),
        ]
        assert finding.event_count == 2
        assert finding.max_stall_ms == pytest.approx(500.0)
        assert finding.latest_stack == [CALL_SITE, HANDLER]

    async def test_filters_by_app_instance_and_window(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        db_svc, _ = db
        await insert_event(db_svc, detected_ts=2000.0)
        await insert_event(db_svc, detected_ts=500.0)  # before the window
        await insert_event(db_svc, instance_index=1, detected_ts=2000.0)
        await insert_event(db_svc, app_key="other_app", detected_ts=2000.0)

        result = await query_service.get_blocking_findings(app_key="my_app", instance_index=0, since=1000.0)

        assert [(f.app_key, f.event_count) for f in result.findings] == [("my_app", 1)]

    async def test_all_apps_query_spans_apps_and_instances(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        db_svc, _ = db
        await insert_event(db_svc)
        await insert_event(db_svc, instance_index=1)
        await insert_event(db_svc, app_key="other_app")

        result = await query_service.get_blocking_findings(app_key=None, instance_index=None, since=None)

        assert sorted((f.app_key, f.event_count) for f in result.findings) == [("my_app", 2), ("other_app", 1)]

    async def test_unattributed_rows_are_never_credited_to_an_app(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """A displaced row stays off the app's findings even when its stack holds the app's code."""
        db_svc, _ = db
        await insert_event(db_svc, app_key=None, instance_index=None, reason="displaced")

        result = await query_service.get_blocking_findings(app_key=None, instance_index=None, since=None)

        assert result.findings == []

    async def test_truncates_at_the_row_cap(
        self, query_service: TelemetryQueryService, db: DbFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_svc, _ = db
        monkeypatch.setattr(blocking_queries, "BLOCKING_ROW_LIMIT", 2)
        for ts in (1000.0, 2000.0, 3000.0):
            await insert_event(db_svc, detected_ts=ts)

        result = await query_service.get_blocking_findings(app_key="my_app", instance_index=0, since=None)

        assert result.truncated
        [finding] = result.findings
        assert (finding.event_count, finding.last_seen_ts) == (2, 3000.0)


class TestUnattributedBlocking:
    async def test_summarizes_only_unattributed_rows(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        db_svc, _ = db
        await insert_event(db_svc, app_key=None, instance_index=None, reason="displaced", stall_duration_ms=5000.0)
        await insert_event(db_svc, app_key=None, instance_index=None, reason="framework", frames=None)
        await insert_event(db_svc)  # attributed: not part of the diagnostics view

        result = await query_service.get_unattributed_blocking(since=None)

        assert (result.total_count, result.displaced_count, result.framework_count) == (2, 1, 1)
        assert result.max_stall_ms == pytest.approx(5000.0)
        app_frames = [s.app_frame.display_path if s.app_frame else None for s in result.recent]
        assert sorted(app_frames, key=str) == [None, "helper.py"]


class TestBlockingEventCounts:
    async def test_counts_attributed_rows_per_app_in_window(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        db_svc, _ = db
        await insert_event(db_svc, detected_ts=2000.0)
        await insert_event(db_svc, detected_ts=2000.0, instance_index=1)
        await insert_event(db_svc, detected_ts=500.0)
        await insert_event(db_svc, app_key=None, instance_index=None, reason="displaced", detected_ts=2000.0)

        assert await query_service.get_blocking_event_counts(since=1000.0) == {"my_app": 2}
        assert await query_service.get_blocking_event_counts(since=None) == {"my_app": 3}
