"""ListenerMissRecorder without a database: which listeners record, how entries key, and failed-flush accounting.

Spec 151: parent D4 (app tier only), D3 (filter in the key), and the Posture's failure handling (a write that
provably didn't run merges back for the next flush; any other failure, or one on the final flush, is counted and
warned about once per episode).
"""

import asyncio
import logging
import sqlite3
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.listener_miss_recorder import MAX_FLUSH_RETRIES, ListenerMissRecorder
from hassette.core.pipeline_counters import PipelineCounter
from hassette.event_handling import predicates as P
from hassette.testing import create_state_change_event
from tests.support.helpers import create_listener
from tests.support.mock_hassette import make_mock_hassette

ENTITY_ID = "light.porch"


@pytest.fixture
def hassette() -> MagicMock:
    hassette = make_mock_hassette()
    hassette.try_database_service.return_value = hassette.database_service
    return hassette


def registered(source_tier: str = "app", db_id: int | None = 7):
    listener = create_listener(
        topic=f"hass.event.state_changed.{ENTITY_ID}",
        source_tier=source_tier,  # pyright: ignore[reportArgumentType]
        where=[P.StateTo("on"), P.StateFrom("off")],
    )
    if db_id is not None:
        listener.mark_registered(db_id)
    return listener


def event(new: str = "dim"):
    return create_state_change_event(entity_id=ENTITY_ID, old_value="off", new_value=new)


def failing_submit(exc: BaseException) -> "Callable[[Coroutine[Any, Any, Any]], None]":
    """A ``submit`` side effect that fails as the write queue does: the coroutine is closed, then ``exc`` raises."""

    def submit(coro: Coroutine[Any, Any, Any]) -> None:
        coro.close()
        raise exc

    return submit


class TestReporterFor:
    def test_registered_app_listener_gets_a_reporter(self, hassette: MagicMock) -> None:
        assert ListenerMissRecorder(hassette).reporter_for(registered()) is not None

    @pytest.mark.parametrize(("source_tier", "db_id"), [("framework", 7), ("app", None)])
    def test_framework_or_unregistered_listener_records_nothing(
        self, hassette: MagicMock, source_tier: str, db_id: int | None
    ) -> None:
        assert ListenerMissRecorder(hassette).reporter_for(registered(source_tier, db_id)) is None

    def test_no_database_records_nothing(self) -> None:
        assert ListenerMissRecorder(make_mock_hassette()).reporter_for(registered()) is None


class TestRecord:
    def test_entries_key_on_reason_and_filter_and_keep_the_last_event(self, hassette: MagicMock) -> None:
        recorder = ListenerMissRecorder(hassette)
        listener = registered()
        first, last = event("dim"), event("red")

        recorder.record(listener, "filter", first, filter_index=0)
        recorder.record(listener, "filter", last, filter_index=0)
        recorder.record(listener, "filter", event(), filter_index=1)
        recorder.record(listener, "throttled", event())

        by_key = {(e.reason, e.filter_index): e for e in recorder.entries.values()}
        assert set(by_key) == {("filter", 0), ("filter", 1), ("throttled", None)}
        entry = by_key[("filter", 0)]
        assert (entry.count, entry.last_event) == (2, last)
        assert entry.first_ts <= entry.last_ts


class TestFailedFlush:
    async def test_failed_flush_drops_the_batch_counts_it_and_warns_once_per_episode(
        self, hassette: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        hassette.database_service.submit = AsyncMock(side_effect=failing_submit(RuntimeError("queue gone")))
        recorder = ListenerMissRecorder(hassette)
        listener = registered()

        with caplog.at_level(logging.WARNING, logger="hassette.core.listener_miss_recorder"):
            recorder.record(listener, "filter", event(), filter_index=0)
            recorder.record(listener, "busy", event())
            await recorder.flush()
            recorder.record(listener, "busy", event())
            await recorder.flush()

        assert recorder.entries == {}
        assert hassette.pipeline_counters.get(PipelineCounter.LISTENER_MISS_FLUSH_FAILED) == 3
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
        assert hassette.database_service.submit.await_count == 2

    async def test_cancelled_flush_counts_its_batch_and_re_raises(self, hassette: MagicMock) -> None:
        """The periodic flush cancelled while waiting on the write queue at shutdown still counts its batch."""
        hassette.database_service.submit = AsyncMock(side_effect=failing_submit(asyncio.CancelledError()))
        recorder = ListenerMissRecorder(hassette)
        recorder.record(registered(), "busy", event())

        with pytest.raises(asyncio.CancelledError):
            await recorder.flush()

        assert hassette.pipeline_counters.get(PipelineCounter.LISTENER_MISS_FLUSH_FAILED) == 1

    @pytest.mark.parametrize("error", [TimeoutError(), sqlite3.OperationalError("database is locked")])
    async def test_unwritten_batch_merges_back_into_newer_entries(self, hassette: MagicMock, error: Exception) -> None:
        """A write that never ran keeps its batch; an entry recorded since the swap keeps its newer last event."""
        recorder = ListenerMissRecorder(hassette)
        listener = registered()
        newer = event("red")

        def fail_after_new_record(coro: Coroutine[Any, Any, Any]) -> None:
            coro.close()
            recorder.record(listener, "busy", newer)
            raise error

        hassette.database_service.submit = AsyncMock(side_effect=fail_after_new_record)
        recorder.record(listener, "busy", event())
        recorder.record(listener, "throttled", event())
        first_busy_ts = next(iter(recorder.entries.values())).first_ts

        await recorder.flush()

        by_reason = {entry.reason: entry for entry in recorder.entries.values()}
        assert set(by_reason) == {"busy", "throttled"}
        busy = by_reason["busy"]
        assert (busy.count, busy.first_ts, busy.last_event) == (2, first_busy_ts, newer)
        assert hassette.pipeline_counters.get(PipelineCounter.LISTENER_MISS_FLUSH_FAILED) == 0

    async def test_final_flush_counts_an_unwritten_batch_as_lost(self, hassette: MagicMock) -> None:
        """The shutdown flush has no later flush to merge back into, so a timed-out write is a counted loss."""
        hassette.database_service.submit = AsyncMock(side_effect=failing_submit(TimeoutError()))
        recorder = ListenerMissRecorder(hassette)
        recorder.record(registered(), "busy", event())

        await recorder.flush(final=True)

        assert recorder.entries == {}
        assert hassette.pipeline_counters.get(PipelineCounter.LISTENER_MISS_FLUSH_FAILED) == 1

    async def test_retries_stop_after_the_bound_and_count_the_loss(
        self, hassette: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A write that keeps not running merges back MAX_FLUSH_RETRIES times, then drops, counts and warns."""
        hassette.database_service.submit = AsyncMock(side_effect=failing_submit(TimeoutError()))
        recorder = ListenerMissRecorder(hassette)
        recorder.record(registered(), "busy", event())

        with caplog.at_level(logging.WARNING, logger="hassette.core.listener_miss_recorder"):
            for _ in range(MAX_FLUSH_RETRIES):
                await recorder.flush()
                assert len(recorder.entries) == 1
            await recorder.flush()

        assert recorder.entries == {}
        assert hassette.pipeline_counters.get(PipelineCounter.LISTENER_MISS_FLUSH_FAILED) == 1
        assert "they are dropped" in caplog.records[-1].getMessage()

    async def test_empty_flush_writes_nothing(self, hassette: MagicMock) -> None:
        hassette.database_service.submit = AsyncMock()
        await ListenerMissRecorder(hassette).flush()
        hassette.database_service.submit.assert_not_awaited()
