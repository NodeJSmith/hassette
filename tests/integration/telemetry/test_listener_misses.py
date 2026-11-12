"""listener_misses rows against the real schema: the recorder's flush, the merging upsert, cascade, and the read.

Spec 151: D3 (filter in the rollup key), D5 (reason codes), D6 (caused_by on miss reads), and the Summary's
flush and storage rules (additive upsert, deleted listeners skipped, rows deleted with their listener).
"""

import time
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from hassette.bus.listeners import Listener
from hassette.core import listener_miss_recorder as recorder_module
from hassette.core.database_service import DatabaseService
from hassette.core.listener_miss_recorder import ListenerMissRecorder, ListenerMissRow
from hassette.core.telemetry.helpers import LISTENER_MISS_NO_FILTER
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.event_handling import predicates as P
from hassette.testing import create_state_change_event
from tests.support.helpers import create_listener

from .helpers import DbFixture, commit_returning_id, insert_listener

ENTITY_ID = "light.porch"
HOUR = 1_700_000_000.0 - 1_700_000_000.0 % 3600


def make_row(listener_id: int, **overrides: Any) -> ListenerMissRow:
    row = ListenerMissRow(
        listener_id=listener_id,
        hour_ts=HOUR,
        reason="filter",
        filter="state is 'on'",
        count=2,
        first_ts=HOUR + 10,
        last_ts=HOUR + 20,
        trigger_topic="hass.event.state_changed",
        trigger_entity_id=ENTITY_ID,
        trigger_old_value="off",
        trigger_new_value="dim",
        trigger_context_id="ctx-1",
        trigger_parent_id=None,
        trigger_origin="LOCAL",
    )
    return replace(row, **overrides)


async def upsert(db_svc: DatabaseService, *rows: ListenerMissRow) -> None:
    await db_svc.submit(TelemetryRepository(db_svc).upsert_listener_misses(list(rows)))


async def fetch_misses(db_svc: DatabaseService) -> list[dict[str, Any]]:
    cursor = await db_svc.db.execute("SELECT * FROM listener_misses ORDER BY id")
    return [dict(row) for row in await cursor.fetchall()]


def registered_listener(db_id: int) -> Listener:
    listener = create_listener(
        topic=f"hass.event.state_changed.{ENTITY_ID}", app_key="porch", where=[P.StateTo("on"), P.StateFrom("off")]
    )
    listener.mark_registered(db_id)
    return listener


class TestUpsert:
    async def test_same_key_adds_count_keeps_first_and_takes_newer_last(self, db: DbFixture) -> None:
        db_svc, _ = db
        listener_id = await insert_listener(db_svc)
        await upsert(db_svc, make_row(listener_id))
        await upsert(
            db_svc, make_row(listener_id, count=3, first_ts=HOUR + 5, last_ts=HOUR + 30, trigger_new_value="red")
        )

        [row] = await fetch_misses(db_svc)
        assert (row["count"], row["first_ts"], row["last_ts"]) == (5, HOUR + 5, HOUR + 30)
        assert row["trigger_new_value"] == "red"

    async def test_older_rollup_does_not_replace_the_last_event(self, db: DbFixture) -> None:
        db_svc, _ = db
        listener_id = await insert_listener(db_svc)
        await upsert(db_svc, make_row(listener_id, last_ts=HOUR + 50, trigger_new_value="newest"))
        await upsert(db_svc, make_row(listener_id, last_ts=HOUR + 20, trigger_new_value="older"))

        [row] = await fetch_misses(db_svc)
        assert (row["count"], row["last_ts"], row["trigger_new_value"]) == (4, HOUR + 50, "newest")

    async def test_each_reason_filter_and_hour_is_its_own_row(self, db: DbFixture) -> None:
        db_svc, _ = db
        listener_id = await insert_listener(db_svc)
        await upsert(
            db_svc,
            make_row(listener_id),
            make_row(listener_id, filter="previous state is 'off'"),
            make_row(listener_id, reason="throttled", filter=LISTENER_MISS_NO_FILTER),
            make_row(listener_id, hour_ts=HOUR + 3600),
        )

        assert len(await fetch_misses(db_svc)) == 4

    async def test_row_for_a_deleted_listener_is_skipped_without_failing_the_batch(self, db: DbFixture) -> None:
        db_svc, _ = db
        kept = await insert_listener(db_svc, name="kept")
        await upsert(db_svc, make_row(kept), make_row(999_999))

        assert [row["listener_id"] for row in await fetch_misses(db_svc)] == [kept]

    async def test_deleting_the_listener_deletes_its_rows(self, db: DbFixture) -> None:
        db_svc, _ = db
        listener_id = await insert_listener(db_svc)
        await upsert(db_svc, make_row(listener_id))
        cursor = await db_svc.db.execute("DELETE FROM listeners WHERE id = ?", (listener_id,))
        await commit_returning_id(db_svc, cursor)

        assert await fetch_misses(db_svc) == []


class TestRecorderFlush:
    async def test_flush_writes_one_row_per_filter_with_its_summary(
        self, db_hassette: MagicMock, db: DbFixture
    ) -> None:
        db_svc, _ = db
        listener = registered_listener(await insert_listener(db_svc))
        recorder = ListenerMissRecorder(db_hassette)
        report = recorder.reporter_for(listener)
        assert report is not None

        report(
            "filter", create_state_change_event(entity_id=ENTITY_ID, old_value="off", new_value="dim"), filter_index=0
        )
        report(
            "filter", create_state_change_event(entity_id=ENTITY_ID, old_value="off", new_value="red"), filter_index=0
        )
        report("filter", create_state_change_event(entity_id=ENTITY_ID, old_value="on", new_value="on"), filter_index=1)
        await recorder.flush()

        rows = {row["filter"]: row for row in await fetch_misses(db_svc)}
        assert set(rows) == {P.StateTo("on").summarize(), P.StateFrom("off").summarize()}
        to_on = rows[P.StateTo("on").summarize()]
        assert (to_on["reason"], to_on["count"], to_on["trigger_entity_id"]) == ("filter", 2, ENTITY_ID)
        assert to_on["trigger_new_value"] is not None
        assert "red" in to_on["trigger_new_value"]
        assert recorder.entries == {}

    async def test_reflush_in_the_same_hour_adds_to_the_row(
        self, db_hassette: MagicMock, db: DbFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_svc, _ = db
        monkeypatch.setattr(recorder_module, "time", SimpleNamespace(time=lambda: HOUR + 60, monotonic=time.monotonic))
        listener = registered_listener(await insert_listener(db_svc))
        recorder = ListenerMissRecorder(db_hassette)
        event = create_state_change_event(entity_id=ENTITY_ID, old_value="off", new_value="on")

        recorder.record(listener, "throttled", event)
        await recorder.flush()
        recorder.record(listener, "throttled", event)
        await recorder.flush()

        [row] = await fetch_misses(db_svc)
        assert (row["reason"], row["filter"], row["count"]) == ("throttled", LISTENER_MISS_NO_FILTER, 2)


class TestRead:
    async def test_newest_last_drop_first_with_since_and_limit(
        self, db: DbFixture, query_service: TelemetryQueryService
    ) -> None:
        db_svc, _ = db
        listener_id = await insert_listener(db_svc)
        await upsert(
            db_svc,
            make_row(listener_id, last_ts=HOUR + 10),
            make_row(listener_id, reason="busy", filter=LISTENER_MISS_NO_FILTER, last_ts=HOUR + 30),
            make_row(listener_id, reason="throttled", filter=LISTENER_MISS_NO_FILTER, last_ts=HOUR + 20),
        )

        misses = await query_service.get_listener_misses(listener_id)
        assert [m.reason for m in misses] == ["busy", "throttled", "filter"]
        assert [m.filter for m in misses] == [None, None, "state is 'on'"]
        assert [m.reason for m in await query_service.get_listener_misses(listener_id, limit=1)] == ["busy"]
        since = await query_service.get_listener_misses(listener_id, since=HOUR + 20)
        assert [m.reason for m in since] == ["busy", "throttled"]

    async def test_trigger_carries_the_last_event_and_caused_by(
        self, db: DbFixture, query_service: TelemetryQueryService
    ) -> None:
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        await upsert(db_svc, make_row(listener_id, trigger_context_id="ctx-write"))
        cursor = await db_svc.db.execute(
            """INSERT INTO api_writes (write_id, session_id, app_key, instance_name, kind, operation, sent_ts,
                                       outcome, context_id)
               VALUES ('w-1', ?, 'porch', 'main', 'call_service', 'light.turn_on', ?, 'success', 'ctx-write')""",
            (session_id, time.time()),
        )
        await commit_returning_id(db_svc, cursor)

        [miss] = await query_service.get_listener_misses(listener_id)
        assert (miss.trigger.entity_id, miss.trigger.old_value, miss.trigger.new_value) == (ENTITY_ID, "off", "dim")
        assert miss.trigger.caused_by is not None
        assert (miss.trigger.caused_by.app_key, miss.trigger.caused_by.operation) == ("porch", "light.turn_on")
