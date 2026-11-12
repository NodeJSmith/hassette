"""Hourly rollups of the events that reached an app listener and didn't run its handler (near-misses).

``BusService`` composes one ``ListenerMissRecorder``. Each app listener's ``HandlerInvoker`` gets a reporter
bound to it at registration (``reporter_for``), and every drop site reports through it with ``Delivery.drop``.
Recording only updates an in-memory entry keyed by listener, hour, reason and filter: no I/O, and the event's
values aren't rendered until the flush. While it runs, ``run_flush_loop`` is the only flusher: every
``FLUSH_INTERVAL_SECONDS`` it swaps the entries out and writes them as one batched upsert that adds to any row
already stored for the same key, and once its stop event is set it flushes once more and returns, so the final
flush at shutdown never overlaps a periodic one. ``start`` runs the loop and ``stop`` ends it, flushing directly only
when no loop is running. ``BusService`` calls both from its own initialize and shutdown hooks.

Recording is best-effort. A failed write loses its batch, which is counted under
``PipelineCounter.LISTENER_MISS_FLUSH_FAILED`` with a paced WARNING; nothing is retried, so a miss is written in
the flush that swapped it out or not at all (prior art: design/research/2026-11-12-telemetry-flush-lifecycle).
"""

import asyncio
import contextlib
import logging
import time
import typing
from dataclasses import dataclass, replace
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

    from hassette import Hassette, TaskBucket
    from hassette.bus.invoker import DropReporter
    from hassette.bus.listeners import Listener
    from hassette.events import AnyEvent

LOGGER = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 30.0
"""How often in-memory rollups are written, and so the longest wait before a near-miss shows in a read
(design/specs/151-listener-near-misses D4)."""


@dataclass(frozen=True, slots=True)
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
    ``last_event``: each record replaces the entry with both updated."""


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
        self.last_loss_warn_monotonic: float | None = None
        self.flush_stop: asyncio.Event | None = None
        """Ends the flush loop; created at each ``start`` so a re-initialized service gets a live loop."""
        self.flush_task: asyncio.Task[None] | None = None
        """The flush loop, the only flusher while it runs; ``stop`` ends it and awaits its last flush."""

    def start(self, task_bucket: "TaskBucket") -> None:
        """Spawn the flush loop on ``task_bucket``."""
        self.flush_stop = asyncio.Event()
        self.flush_task = task_bucket.spawn(self.run_flush_loop(self.flush_stop), name="bus:listener_miss_flush")

    async def stop(self) -> None:
        """Stop the flush loop and await its last flush, or flush directly when no loop is running.

        Only one of the two runs, so a direct flush never overlaps the loop's.
        """
        if self.flush_stop is not None:
            self.flush_stop.set()
        task = self.flush_task
        if task is not None and not task.done():
            await task
        else:
            await self.flush()

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
            self.entries[key] = replace(
                entry, count=entry.count + 1, last_ts=now, last_event=event, is_synthetic=is_synthetic
            )
        except Exception:
            LOGGER.exception("Failed to record a near-miss for %s", listener)

    async def run_flush_loop(self, stop: asyncio.Event) -> None:
        """Flush every ``FLUSH_INTERVAL_SECONDS`` until ``stop`` is set, then flush once more and return.

        The stop check is taken before the flush, so a stop that lands while a flush is writing still gets one more
        flush for the entries recorded during that write. Drops recorded after the last flush aren't written.
        """
        while True:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(FLUSH_INTERVAL_SECONDS):
                    await stop.wait()
            stopping = stop.is_set()
            await self.flush()
            if stopping:
                return

    async def flush(self) -> None:
        """Write every entry accrued since the last flush as one batched upsert.

        The entries are swapped out first, so dispatch keeps recording into a fresh map while the write runs. A
        failed write loses exactly the swapped-out batch, which is counted and warned about. Never raises, except
        ``CancelledError``: a flush cancelled mid-write (the loop, when the shutdown hook awaiting it runs out of
        time) counts and warns about its batch as lost, then re-raises. A write the queue had already started may
        still commit, so that count can overstate the loss.
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
        except Exception as exc:
            self.count_loss(len(entries), exc)
            return
        LOGGER.debug("Flushed %d listener near-miss rollup(s)", len(rows))

    def count_loss(self, lost: int, exc: BaseException) -> None:
        """Count a lost batch and log a WARNING for it, at most once per interval.

        The WARNING is paced like the execution queue's capacity one; the counter counts every loss.
        """
        self.hassette.pipeline_counters.increment(PipelineCounter.LISTENER_MISS_FLUSH_FAILED, lost)
        now = time.monotonic()
        interval = self.hassette.config.lifecycle.command_executor_capacity_warn_rate_limit_seconds
        if self.last_loss_warn_monotonic is not None and now - self.last_loss_warn_monotonic < interval:
            return
        self.last_loss_warn_monotonic = now
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
