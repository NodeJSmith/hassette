"""Hourly rollups of the events that reached an app listener and didn't run its handler (near-misses).

``BusService`` composes one ``ListenerMissRecorder``. Each app listener's ``HandlerInvoker`` gets a reporter
bound to it at registration (``reporter_for``), and every drop site calls it. Recording only updates an
in-memory entry keyed by listener, hour, reason and filter: no I/O, and the event's values aren't rendered until
the flush. A flush every ``FLUSH_INTERVAL_SECONDS`` (and once at shutdown) swaps the entries out and writes them
as one batched upsert that adds to any row already stored for the same key.

Recording is best-effort. A write that provably didn't happen (``submit`` timed out, or SQLite rolled it back with
``OperationalError``) merges its batch back for the next flush, up to ``MAX_FLUSH_RETRIES`` flushes in a row, as the
execution flusher retries the same failures. Any other failure, a retryable one past that bound, and a retryable one
on the final flush at shutdown lose the batch: it is counted under ``PipelineCounter.LISTENER_MISS_FLUSH_FAILED``
with a paced WARNING.
"""

import asyncio
import logging
import sqlite3
import time
import typing
from dataclasses import dataclass
from functools import partial

from hassette.const.misc import SECONDS_PER_HOUR
from hassette.core.execution_record_builder import summarize_trigger
from hassette.core.pipeline_counters import PipelineCounter
from hassette.core.telemetry.helpers import LISTENER_MISS_NO_FILTER
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.event_handling.predicates import summarize_top_level
from hassette.types.types import APP_SOURCE_TIER

if typing.TYPE_CHECKING:
    from hassette_wire import ListenerMissReason

    from hassette import Hassette
    from hassette.bus.listeners import DropReporter, Listener
    from hassette.events import AnyEvent

LOGGER = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 30.0
"""How often in-memory rollups are written, and so the longest wait before a near-miss shows in a read
(design/specs/151-listener-near-misses D4)."""

MAX_FLUSH_RETRIES = 3
"""Consecutive flushes whose write didn't run that merge back before the next one drops and counts its batch; the
same bound as the execution flusher's."""


@dataclass(slots=True)
class MissEntry:
    """One rollup accrued since the last flush: a listener's drops for one reason (and filter) in one hour."""

    listener: "Listener"
    reason: "ListenerMissReason"
    hour_ts: float
    filter_index: int | None
    """Index of the rejecting filter in ``listener.filters``, for ``reason='filter'``; rendered at flush."""
    count: int
    first_ts: float
    last_ts: float
    last_event: "AnyEvent"
    """The last dropped event, summarized at flush with the executions' trigger summary."""
    is_synthetic: bool
    """Whether ``last_event`` was built from the cached state, so its origin is stored as synthetic. Follows
    ``last_event``: each record replaces both."""


@dataclass(frozen=True, slots=True)
class ListenerMissRow:
    """The columns of one ``listener_misses`` upsert."""

    listener_id: int
    hour_ts: float
    reason: "ListenerMissReason"
    filter: str
    count: int
    first_ts: float
    last_ts: float
    trigger_topic: str | None
    trigger_entity_id: str | None
    trigger_old_value: str | None
    trigger_new_value: str | None
    trigger_context_id: str | None
    trigger_parent_id: str | None
    trigger_origin: str | None


class ListenerMissRecorder:
    """Accrues near-miss rollups in memory and flushes them to ``listener_misses``."""

    def __init__(self, hassette: "Hassette") -> None:
        self.hassette = hassette
        self.entries: dict[tuple[int, float, ListenerMissReason, int | None], MissEntry] = {}
        """Rollups since the last flush, keyed by in-memory listener id, hour, reason and filter index."""
        self.last_loss_warn_ts: float | None = None
        self.retries = 0
        """Consecutive flushes merged back because their write didn't run; reset by a successful write."""

    def reporter_for(self, listener: "Listener") -> "DropReporter | None":
        """The reporter to bind to ``listener``, or None for a listener whose near-misses aren't recorded.

        Only registered app listeners record: framework listeners and ones without a ``db_id`` don't, and nothing
        records when no ``DatabaseService`` is wired.
        """
        if listener.identity.source_tier != APP_SOURCE_TIER or listener.db_id is None:
            return None
        if self.hassette.try_database_service() is None:
            return None
        return partial(self.record, listener)

    def record(
        self,
        listener: "Listener",
        reason: "ListenerMissReason",
        event: "AnyEvent",
        *,
        filter_index: int | None = None,
        is_synthetic: bool = False,
    ) -> None:
        """Count one dropped event in its hour's entry. Never raises: recording must not affect dispatch."""
        try:
            now = time.time()
            hour_ts = now - now % SECONDS_PER_HOUR
            key = (listener.listener_id, hour_ts, reason, filter_index)
            entry = self.entries.get(key)
            if entry is None:
                self.entries[key] = MissEntry(
                    listener=listener,
                    reason=reason,
                    hour_ts=hour_ts,
                    filter_index=filter_index,
                    count=1,
                    first_ts=now,
                    last_ts=now,
                    last_event=event,
                    is_synthetic=is_synthetic,
                )
                return
            entry.count += 1
            entry.last_ts = now
            entry.last_event = event
            entry.is_synthetic = is_synthetic
        except Exception:
            LOGGER.exception("Failed to record a near-miss for %s", listener)

    async def run_flush_loop(self) -> None:
        """Flush every ``FLUSH_INTERVAL_SECONDS`` until cancelled."""
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            await self.flush()

    async def flush(self, *, final: bool = False) -> None:
        """Write every entry accrued since the last flush as one batched upsert.

        The entries are swapped out first, so dispatch keeps recording into a fresh map while the write runs.
        A ``TimeoutError`` or ``sqlite3.OperationalError`` means nothing was written, so the batch merges back into
        the map for the next flush. That stops after ``MAX_FLUSH_RETRIES`` in a row, and on the ``final`` flush at
        shutdown, which has no next flush. Any other failure loses exactly the swapped-out batch, which is counted
        and warned about. Never raises, except ``CancelledError``: a flush cancelled mid-write (the periodic task at
        shutdown) counts and warns about its batch as lost, then re-raises. A write the queue had already started
        may still commit, so that count can overstate the loss; a cancelled batch is never merged back, because the
        upsert is additive.
        """
        if not self.entries:
            return
        entries, self.entries = self.entries, {}
        try:
            rows = [build_row(entry) for entry in entries.values()]
            database = self.hassette.database_service
            await database.submit(TelemetryRepository(database).upsert_listener_misses(rows))
        except asyncio.CancelledError as exc:
            self.count_loss(len(entries), exc)
            raise  # task cancellation must propagate
        except (TimeoutError, sqlite3.OperationalError) as exc:
            if final or self.retries >= MAX_FLUSH_RETRIES:
                self.retries = 0
                self.count_loss(len(entries), exc)
                return
            self.retries += 1
            self.merge_back(entries)
            LOGGER.warning(
                "Couldn't write %d listener near-miss rollup(s); keeping them for the next flush (retry %d of %d)",
                len(entries),
                self.retries,
                MAX_FLUSH_RETRIES,
                exc_info=exc,
            )
            return
        except Exception as exc:
            self.count_loss(len(entries), exc)
            return
        self.retries = 0
        LOGGER.debug("Flushed %d listener near-miss rollup(s)", len(rows))

    def merge_back(self, batch: dict[tuple[int, float, "ListenerMissReason", int | None], MissEntry]) -> None:
        """Return an unwritten batch to the map, folding it into any entry recorded for the same key since the swap.

        An entry recorded since the swap is newer, so it keeps its last event and gains the batch's count and
        earlier first time.
        """
        for key, old in batch.items():
            current = self.entries.get(key)
            if current is None:
                self.entries[key] = old
                continue
            current.count += old.count
            current.first_ts = min(current.first_ts, old.first_ts)

    def count_loss(self, lost: int, exc: BaseException) -> None:
        """Count a lost batch and log a WARNING for it, at most once per interval.

        The WARNING is paced like the execution queue's capacity one. Retry WARNINGs don't share this pacing, so
        they never hide a loss.
        """
        self.hassette.pipeline_counters.increment(PipelineCounter.LISTENER_MISS_FLUSH_FAILED, lost)
        now = time.monotonic()
        interval = self.hassette.config.lifecycle.command_executor_capacity_warn_rate_limit_seconds
        if self.last_loss_warn_ts is not None and now - self.last_loss_warn_ts < interval:
            return
        self.last_loss_warn_ts = now
        LOGGER.warning(
            "Failed to write %d listener near-miss rollup(s); they are dropped (counted under %s)",
            lost,
            PipelineCounter.LISTENER_MISS_FLUSH_FAILED.name,
            exc_info=exc,
        )


def build_row(entry: MissEntry) -> ListenerMissRow:
    """Render an entry's filter summary and last event into the row the upsert writes."""
    listener = entry.listener
    if listener.db_id is None:
        raise RuntimeError(f"near-miss recorded for unregistered listener {listener!r}")
    if entry.filter_index is None:
        filter_summary = LISTENER_MISS_NO_FILTER
    else:
        filter_summary = summarize_top_level(listener.filters[entry.filter_index])
    trigger = summarize_trigger(entry.last_event, listener, is_synthetic=entry.is_synthetic)
    return ListenerMissRow(
        listener_id=listener.db_id,
        hour_ts=entry.hour_ts,
        reason=entry.reason,
        filter=filter_summary,
        count=entry.count,
        first_ts=entry.first_ts,
        last_ts=entry.last_ts,
        **trigger,
    )
