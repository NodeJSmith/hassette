"""api_writes rows against the real schema: insert and update, the execution read, caused_by, and the startup sweep.

Spec 149: D3 (row shape), D5 (caused_by), D6 (writes on the execution read), D8 (insert at send, update on
resolution), D9 (startup sweep of earlier runs' pending rows).
"""

import logging
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from hassette.context import CURRENT_EXECUTION_ID
from hassette.core.api_write_recorder import ApiWriteHandle, ApiWriteRecorder
from hassette.core.database_service import DatabaseService
from hassette.core.session_manager import SessionManager
from hassette.core.telemetry.query_service import TelemetryQueryService

from .helpers import DbFixture, commit_returning_id, drain_db_writes, insert_listener

APP_KEY = "porch"
INSTANCE = "main"


@pytest.fixture
def recorder(db_hassette: MagicMock, db: DbFixture) -> ApiWriteRecorder:  # noqa: ARG001
    return ApiWriteRecorder(db_hassette)


def begin(
    recorder: ApiWriteRecorder,
    *,
    execution_id: str | None = "exec-1",
    kind: Any = "call_service",
    operation: str | None = "light.turn_on",
    target: dict[str, list[str]] | None = None,
    data: Any = None,
) -> ApiWriteHandle:
    token = CURRENT_EXECUTION_ID.set(execution_id)
    try:
        return recorder.begin(
            api_logger=logging.getLogger("hassette.test"),
            app_key=APP_KEY,
            instance_name=INSTANCE,
            kind=kind,
            operation=operation,
            target=target if target is not None else {"entity_id": ["light.porch"]},
            data=data,
        )
    finally:
        CURRENT_EXECUTION_ID.reset(token)


async def fetch_write(db_svc: DatabaseService, write_id: str) -> dict[str, Any]:
    cursor = await db_svc.db.execute("SELECT * FROM api_writes WHERE write_id = ?", (write_id,))
    row = await cursor.fetchone()
    assert row is not None
    return dict(row)


async def insert_handler_run(db_svc: DatabaseService, session_id: int, execution_id: str, context_id: str) -> None:
    listener_id = await insert_listener(db_svc, app_key="watcher")
    cursor = await db_svc.db.execute(
        """INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status,
                                   execution_id, trigger_context_id)
           VALUES ('handler', ?, ?, ?, 1.0, 'success', ?, ?)""",
        (listener_id, session_id, time.time(), execution_id, context_id),
    )
    await commit_returning_id(db_svc, cursor)


class TestRowLifecycle:
    async def test_insert_at_send_then_outcome(self, recorder: ApiWriteRecorder, db: DbFixture) -> None:
        db_svc, session_id = db
        handle = begin(recorder, data={"brightness": 200})
        await drain_db_writes(db_svc)

        pending = await fetch_write(db_svc, handle.write_id)
        assert pending["outcome"] == "pending"
        assert pending["resolved_ts"] is None
        assert (pending["app_key"], pending["instance_name"], pending["session_id"]) == (APP_KEY, INSTANCE, session_id)
        assert (pending["execution_id"], pending["kind"], pending["operation"]) == (
            "exec-1",
            "call_service",
            "light.turn_on",
        )
        assert pending["target"] == '{"entity_id":["light.porch"]}'
        assert pending["data"] == '{"brightness":200}'

        handle.resolve("success", context_id="ctx-1")
        await drain_db_writes(db_svc)

        resolved = await fetch_write(db_svc, handle.write_id)
        assert (resolved["outcome"], resolved["context_id"]) == ("success", "ctx-1")
        assert resolved["resolved_ts"] is not None

    async def test_rejection_stores_code_and_message(self, recorder: ApiWriteRecorder, db: DbFixture) -> None:
        db_svc, _ = db
        handle = begin(recorder)
        handle.resolve("rejected", error_code="not_found", error_message="no such service")
        await drain_db_writes(db_svc)

        row = await fetch_write(db_svc, handle.write_id)
        assert (row["outcome"], row["error_code"], row["error_message"]) == ("rejected", "not_found", "no such service")

    async def test_unresolved_keeps_resolved_ts_null(self, recorder: ApiWriteRecorder, db: DbFixture) -> None:
        db_svc, _ = db
        handle = begin(recorder)
        handle.resolve("unresolved")
        await drain_db_writes(db_svc)

        row = await fetch_write(db_svc, handle.write_id)
        assert (row["outcome"], row["resolved_ts"], row["error_code"]) == ("unresolved", None, None)


class TestExecutionRead:
    async def test_writes_by_execution_ordered_and_capped(
        self, recorder: ApiWriteRecorder, db: DbFixture, query_service: TelemetryQueryService
    ) -> None:
        db_svc, _ = db
        handles = [begin(recorder, operation=f"light.op_{i}") for i in range(3)]
        begin(recorder, execution_id="other")
        await drain_db_writes(db_svc)

        writes, truncated = await query_service.get_api_writes_by_execution("exec-1", limit=2)

        assert [w.write_id for w in writes] == [h.write_id for h in handles[:2]]
        assert truncated is True
        assert writes[0].target == {"entity_id": ["light.porch"]}
        assert writes[0].outcome == "pending"
        all_writes, all_truncated = await query_service.get_api_writes_by_execution("exec-1", limit=3)
        assert (len(all_writes), all_truncated) == (3, False)


class TestCausedBy:
    async def test_handler_run_names_the_write_whose_context_fired_it(
        self, recorder: ApiWriteRecorder, db: DbFixture, query_service: TelemetryQueryService
    ) -> None:
        db_svc, session_id = db
        await insert_handler_run(db_svc, session_id, "run-1", "ctx-1")
        handle = begin(recorder, execution_id="exec-1")
        await drain_db_writes(db_svc)

        before = await query_service.get_execution_by_id("run-1")
        assert before is not None
        assert before.trigger is not None
        assert before.trigger.caused_by is None  # the listener ran before the reply's context id landed

        handle.resolve("success", context_id="ctx-1")
        await drain_db_writes(db_svc)

        after = await query_service.get_execution_by_id("run-1")
        assert after is not None
        assert after.trigger is not None
        caused_by = after.trigger.caused_by
        assert caused_by is not None
        assert (caused_by.app_key, caused_by.instance_name, caused_by.execution_id) == (APP_KEY, INSTANCE, "exec-1")
        assert (caused_by.kind, caused_by.operation) == ("call_service", "light.turn_on")

    async def test_repeated_context_matches_the_earliest_write_once(
        self, recorder: ApiWriteRecorder, db: DbFixture, query_service: TelemetryQueryService
    ) -> None:
        db_svc, session_id = db
        await insert_handler_run(db_svc, session_id, "run-2", "ctx-dup")
        first = begin(recorder, execution_id=None, kind="set_state", operation=None)
        second = begin(recorder, execution_id="exec-2")
        first.resolve("success", context_id="ctx-dup")
        second.resolve("success", context_id="ctx-dup")
        await drain_db_writes(db_svc)

        runs = await query_service.get_executions(kind="handler")
        matching = [r for r in runs if r.execution_id == "run-2"]
        assert len(matching) == 1
        assert matching[0].trigger is not None
        caused_by = matching[0].trigger.caused_by
        assert caused_by is not None
        assert (caused_by.execution_id, caused_by.kind, caused_by.operation) == (None, "set_state", None)


class TestStartupSweep:
    async def test_earlier_runs_pending_rows_become_unresolved(
        self, recorder: ApiWriteRecorder, db: DbFixture, db_hassette: MagicMock
    ) -> None:
        db_svc, _ = db
        pending = begin(recorder)
        done = begin(recorder)
        done.resolve("success", context_id="ctx-1")
        db_hassette.try_session_id.return_value = None
        orphan = begin(recorder)  # NULL session_id: sent before the session existed
        await drain_db_writes(db_svc)

        manager = SessionManager.__new__(SessionManager)  # bypass Resource wiring; only these two are read
        manager._database_service = db_svc
        manager.logger = MagicMock()
        await db_svc.submit(manager._do_mark_orphaned_sessions())

        for handle in (pending, orphan):
            row = await fetch_write(db_svc, handle.write_id)
            assert (row["outcome"], row["resolved_ts"]) == ("unresolved", None)
        assert (await fetch_write(db_svc, done.write_id))["outcome"] == "success"
