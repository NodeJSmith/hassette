"""lifecycle_events rows against the real schema: what each kind stores, the drop paths, and session retention.

Spec 152: D5 (columns and per-kind details), Posture (best-effort writer that never raises), parent D12 (the
session delete guard).
"""

import json
import logging
import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from hassette_wire import ResourceStatus
from whenever import ZonedDateTime

from hassette.core.app_registry import StatusChange
from hassette.core.database_service import DatabaseService
from hassette.core.pipeline_counters import PipelineCounter
from hassette.core.session_manager import SessionManager
from hassette.core.telemetry.lifecycle_rows import (
    ConnectionDetails,
    LifecycleChange,
    app_change,
    record_app_change,
    record_block_change,
    record_connection_change,
)
from hassette.schemas.app_snapshots import NeedsRestartInfo
from hassette.types.enums import BlockReason, ConnectionState

from .helpers import DbFixture, drain_db_writes

DROPPED = PipelineCounter.LIFECYCLE_ROWS_DROPPED


@pytest.fixture
def manager(db_hassette: MagicMock, db: DbFixture) -> SessionManager:
    db_svc, session_id = db
    manager = SessionManager(db_hassette, database_service=db_svc, parent=None)
    manager._session_id = session_id
    db_hassette.session_manager = manager
    return manager


async def fetch_rows(db_svc: DatabaseService) -> list[dict[str, Any]]:
    cursor = await db_svc.db.execute("SELECT * FROM lifecycle_events ORDER BY id")
    return [dict(row) for row in await cursor.fetchall()]


def change(**overrides: Any) -> StatusChange:
    fields: dict[str, Any] = {
        "app_key": "porch",
        "instance_name": "main",
        "class_name": "PorchApp",
        "previous": ResourceStatus.STARTING,
        "status": ResourceStatus.RUNNING,
    }
    return StatusChange(**(fields | overrides))


class TestRowsPerKind:
    async def test_app_row_stores_previous_and_new_status(
        self, db_hassette: MagicMock, manager: SessionManager, db: DbFixture
    ) -> None:
        db_svc, session_id = db
        before = time.time()
        record_app_change(db_hassette, change())
        await drain_db_writes(db_svc)

        [row] = await fetch_rows(db_svc)
        assert (row["session_id"], row["kind"], row["app_key"], row["instance_name"]) == (
            session_id,
            "app",
            "porch",
            "main",
        )
        assert (row["from_status"], row["to_status"]) == ("starting", "running")
        assert row["details"] == "{}"
        assert row["ts"] >= before

    async def test_failed_app_row_carries_exception_type_and_needs_restart(
        self, db_hassette: MagicMock, manager: SessionManager, db: DbFixture
    ) -> None:
        db_svc, _ = db
        flag = NeedsRestartInfo(
            reason="teardown left tasks running",
            flagged_at=ZonedDateTime(2026, 11, 15, 5, tz="UTC"),
            pending_tasks=("poll",),
        )
        record_app_change(db_hassette, change(status=ResourceStatus.FAILED, error=KeyError("x"), needs_restart=flag))
        await drain_db_writes(db_svc)

        [row] = await fetch_rows(db_svc)
        assert row["to_status"] == "failed"
        assert json.loads(row["details"]) == {
            "exception_type": "KeyError",
            "needs_restart_reason": "teardown left tasks running",
            "pending_tasks": ["poll"],
        }

    async def test_connection_row_has_no_subject_and_only_known_details(
        self, db_hassette: MagicMock, manager: SessionManager, db: DbFixture
    ) -> None:
        db_svc, _ = db
        record_connection_change(
            db_hassette, ConnectionState.CONNECTED, ConnectionState.DISCONNECTED, ConnectionDetails(close_code=1006)
        )
        record_connection_change(db_hassette, ConnectionState.DISCONNECTED, ConnectionState.CONNECTING, None)
        await drain_db_writes(db_svc)

        first, second = await fetch_rows(db_svc)
        assert (first["kind"], first["app_key"], first["instance_name"]) == ("connection", None, None)
        assert (first["from_status"], first["to_status"]) == ("connected", "disconnected")
        assert json.loads(first["details"]) == {"close_code": 1006}
        assert second["details"] == "{}"
        assert first["id"] < second["id"]

    async def test_block_row_has_app_key_only_and_no_from_status(
        self, db_hassette: MagicMock, manager: SessionManager, db: DbFixture
    ) -> None:
        db_svc, _ = db
        record_block_change(db_hassette, "porch", "removed", BlockReason.ONLY_APP)
        await drain_db_writes(db_svc)

        [row] = await fetch_rows(db_svc)
        assert (row["kind"], row["app_key"], row["instance_name"], row["from_status"], row["to_status"]) == (
            "block",
            "porch",
            None,
            None,
            "removed",
        )
        assert json.loads(row["details"]) == {"reason": "only_app"}


class TestDrops:
    """Every row that never reaches the queue is counted and warned about; nothing raises into the owner."""

    async def test_no_session_is_a_counted_drop(
        self, db_hassette: MagicMock, manager: SessionManager, db: DbFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        db_svc, _ = db
        manager._session_id = None
        with caplog.at_level(logging.WARNING):
            record_app_change(db_hassette, change())
        await drain_db_writes(db_svc)

        assert await fetch_rows(db_svc) == []
        assert db_hassette.pipeline_counters.get(DROPPED) == 1
        assert "Could not queue lifecycle row (no session)" in caplog.text

    async def test_full_queue_is_a_counted_drop_with_one_paced_warning(
        self,
        db_hassette: MagicMock,
        manager: SessionManager,
        db: DbFixture,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        db_svc, _ = db

        def refuse(coro: Any) -> bool:
            coro.close()
            return False

        monkeypatch.setattr(db_svc, "enqueue", refuse)
        with caplog.at_level(logging.WARNING):
            record_app_change(db_hassette, change())
            record_app_change(db_hassette, change())

        assert db_hassette.pipeline_counters.get(DROPPED) == 2
        assert caplog.text.count("Could not queue lifecycle row") == 1

    async def test_queue_not_running_is_counted_not_raised(
        self, db_hassette: MagicMock, manager: SessionManager, db: DbFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_svc, _ = db

        def not_live(coro: Any) -> bool:
            coro.close()
            raise RuntimeError("queue not live")

        monkeypatch.setattr(db_svc, "enqueue", not_live)
        record_connection_change(db_hassette, ConnectionState.CONNECTING, ConnectionState.CONNECTED, None)

        assert db_hassette.pipeline_counters.get(DROPPED) == 1

    async def test_a_row_that_fails_to_build_is_counted_not_raised(
        self, db_hassette: MagicMock, manager: SessionManager, db: DbFixture
    ) -> None:
        broken = MagicMock(spec=LifecycleChange)
        broken.details.model_dump_json.side_effect = TypeError("not serializable")
        manager.write_lifecycle_row(lambda: broken)

        assert db_hassette.pipeline_counters.get(DROPPED) == 1

    async def test_missing_session_manager_is_counted_not_raised(self, db_hassette: MagicMock) -> None:
        """The mock's ``session_manager`` is None, standing in for an accessor with no service wired."""
        record_app_change(db_hassette, change())

        assert db_hassette.pipeline_counters.get(DROPPED) == 1

    async def test_a_change_that_fails_to_build_is_counted_and_warned(
        self, db_hassette: MagicMock, manager: SessionManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            record_app_change(db_hassette, MagicMock(spec=StatusChange, needs_restart=object()))

        assert db_hassette.pipeline_counters.get(DROPPED) == 1
        assert "Could not queue lifecycle row (unexpected error)" in caplog.text


def test_app_change_reads_previous_from_the_change() -> None:
    entry = app_change(change(previous=ResourceStatus.NOT_STARTED, status=ResourceStatus.STARTING))
    assert (entry.from_status, entry.to_status) == (ResourceStatus.NOT_STARTED, ResourceStatus.STARTING)
