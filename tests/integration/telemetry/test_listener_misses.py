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
from hassette.core.bus_service import BusService
from hassette.core.database_service import DatabaseService
from hassette.core.listener_miss_recorder import ListenerMissRecorder, ListenerMissRow
from hassette.core.sync_executor import SyncExecutor
from hassette.core.telemetry.helpers import LISTENER_MISS_NO_FILTER
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.event_handling import predicates as P
from hassette.testing import create_state_change_event, wait_for
from tests.support.factories import (
    DEFAULT_TEST_APP_KEY,
    make_bus_service_with_mock_executor,
    make_listener_registration,
)
from tests.support.helpers import create_listener, make_task_bucket
from tests.support.mock_hassette import make_mock_hassette

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


class TestReconcileKeepsMissHistory:
    """A removed listener that never ran but recorded misses keeps them: the misses are its history."""

    async def fetch_retired_at(self, db_svc: DatabaseService, listener_id: int) -> float | None:
        cursor = await db_svc.db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
        row = await cursor.fetchone()
        assert row is not None, f"listener {listener_id} was deleted"
        return row[0]

    async def test_non_live_listener_with_only_misses_is_retired_and_keeps_them(self, db: DbFixture) -> None:
        db_svc, _ = db
        listener_id = await insert_listener(db_svc, app_key=DEFAULT_TEST_APP_KEY)
        await upsert(db_svc, make_row(listener_id))

        await db_svc.submit(TelemetryRepository(db_svc).reconcile_registrations(DEFAULT_TEST_APP_KEY, [], []))

        assert await self.fetch_retired_at(db_svc, listener_id) is not None
        assert [row["listener_id"] for row in await fetch_misses(db_svc)] == [listener_id]

    async def test_once_listener_with_misses_survives_the_once_cleanup(self, db: DbFixture) -> None:
        db_svc, session_id = db
        repo = TelemetryRepository(db_svc)
        listener_id = await db_svc.submit(repo.register_listener(make_listener_registration(once=True, name="once")))
        await upsert(db_svc, make_row(listener_id, reason="once_spent", filter=LISTENER_MISS_NO_FILTER))

        await db_svc.submit(repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], session_id=session_id))

        assert await self.fetch_retired_at(db_svc, listener_id) is not None
        assert [row["listener_id"] for row in await fetch_misses(db_svc)] == [listener_id]

    async def test_non_live_listener_without_executions_or_misses_is_still_deleted(self, db: DbFixture) -> None:
        db_svc, session_id = db
        repo = TelemetryRepository(db_svc)
        plain_id = await insert_listener(db_svc, app_key=DEFAULT_TEST_APP_KEY, name="plain")
        once_id = await db_svc.submit(repo.register_listener(make_listener_registration(once=True, name="once")))

        await db_svc.submit(repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], session_id=session_id))

        cursor = await db_svc.db.execute("SELECT id FROM listeners WHERE id IN (?, ?)", (plain_id, once_id))
        assert await cursor.fetchall() == []


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


def bus_service_on(db_svc: DatabaseService, sync_executor: SyncExecutor) -> BusService:
    """A ``BusService`` whose hassette writes through ``db_svc``, with a task bucket that spawns real tasks.

    This directory's ``db_hassette`` variant is sealed and has no ``sync_executor``, so it can't parent a
    ``Resource``; this builds an unsealed mock with both instead.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.sync_executor = sync_executor
    hassette.database_service = db_svc
    hassette.try_database_service.return_value = db_svc
    service, _ = make_bus_service_with_mock_executor(hassette)
    service.task_bucket = make_task_bucket()
    return service


class TestBusServiceLifecycle:
    """``BusService`` runs the recorder's flush loop, the only flusher, and stops it at shutdown (Summary, Flush)."""

    async def test_periodic_and_shutdown_flushes_both_write(
        self, db: DbFixture, sync_executor: SyncExecutor, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A drop written by a periodic flush and one recorded after it both land; shutdown ends the loop."""
        db_svc, _ = db
        monkeypatch.setattr(recorder_module, "FLUSH_INTERVAL_SECONDS", 0.05)
        listener = registered_listener(await insert_listener(db_svc))
        service = bus_service_on(db_svc, sync_executor)
        report = service._miss_recorder.reporter_for(listener)
        assert report is not None
        event = create_state_change_event(entity_id=ENTITY_ID, old_value="off", new_value="on")

        await service.on_initialize()
        report("busy", event)

        async def written() -> bool:
            return bool(await fetch_misses(db_svc))

        await wait_for(written, timeout=5, desc="the periodic flush's write")
        report("throttled", event)
        await service.on_shutdown()

        task = service._miss_flush_task
        assert task is not None
        assert task.done()
        assert sorted((row["reason"], row["count"]) for row in await fetch_misses(db_svc)) == [
            ("busy", 1),
            ("throttled", 1),
        ]

    async def test_shutdown_mid_interval_writes_pending_misses(
        self, db: DbFixture, sync_executor: SyncExecutor
    ) -> None:
        """Shutdown wakes the loop before its interval ends; its last flush writes what's pending."""
        db_svc, _ = db
        listener = registered_listener(await insert_listener(db_svc))
        service = bus_service_on(db_svc, sync_executor)
        report = service._miss_recorder.reporter_for(listener)
        assert report is not None

        await service.on_initialize()
        report("busy", create_state_change_event(entity_id=ENTITY_ID, old_value="off", new_value="on"))
        await service.on_shutdown()

        assert [(row["reason"], row["count"]) for row in await fetch_misses(db_svc)] == [("busy", 1)]


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
