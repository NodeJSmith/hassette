"""Fixtures for the benchmark suite (``nox -s benchmarks``).

``tests/benchmarks`` is listed in ``norecursedirs``, so the default test run and the CI test
sessions never collect it; the ``benchmarks`` nox session passes the directory explicitly.
"""

import asyncio
import logging
import statistics
from collections.abc import Coroutine, Iterator
from typing import Any, Protocol

import pytest
from fair_async_rlock import FairAsyncRLock
from pytest_benchmark.fixture import BenchmarkFixture
from whenever import TimeDelta

from hassette.scheduler.classes import Job
from hassette.scheduler.job_queue import HeapQueue, _ScheduledJobQueue
from hassette.utils import date_utils
from tests.support.factories import make_scheduled_job

QUEUE_SIZES = [100, 1_000, 10_000]
"""Number of jobs already in the queue when each timed operation runs."""

FIRST_FIRE_OFFSET = TimeDelta(hours=1)
"""How far in the future the earliest queued job fires, so wall-clock time never makes the rest due."""

QUIET_LOGGER = logging.getLogger("hassette.benchmarks.job_queue")
QUIET_LOGGER.setLevel(logging.WARNING)

THROUGHPUT_KEY = pytest.StashKey[list[tuple[str, float]]]()
"""Records/sec results collected by ``record_throughput`` for the end-of-run summary."""


class RunAsync(Protocol):
    def __call__(self, coro: Coroutine[Any, Any, Any], /) -> Any: ...


@pytest.fixture
def run_async() -> Iterator[RunAsync]:
    """Run a coroutine to completion on a private event loop.

    Benchmark tests are synchronous because pytest-benchmark times plain callables; each timed
    call therefore includes one ``run_until_complete`` round trip, a constant overhead shared by
    every size and every saved run.
    """
    loop = asyncio.new_event_loop()
    try:
        yield loop.run_until_complete
    finally:
        loop.close()


def make_queue_jobs(size: int) -> list[Job]:
    """Build ``size`` SCHEDULED jobs firing one second apart, starting an hour from now."""
    first = date_utils.now() + FIRST_FIRE_OFFSET
    return [make_scheduled_job(name=f"bench_job_{i}", next_run=first.add(seconds=i)) for i in range(size)]


def make_job_queue(jobs: list[Job]) -> _ScheduledJobQueue:
    """Build a ``_ScheduledJobQueue`` holding ``jobs``, without a ``Hassette`` instance.

    Bypasses ``Resource.__init__`` (which needs a running ``Hassette``) and installs only what the
    queue operations touch: the lock, the heap, and a logger whose DEBUG calls are filtered out.
    Each call builds a new heap, so mutating one queue never affects another built from the same jobs.
    """
    heap: HeapQueue[Job] = HeapQueue()
    for job in jobs:
        heap.push(job)
    queue = _ScheduledJobQueue.__new__(_ScheduledJobQueue)
    queue._lock = FairAsyncRLock()
    queue._queue = heap
    queue.logger = QUIET_LOGGER
    return queue


def record_throughput(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, *, records_per_round: int) -> None:
    """Report a finished benchmark's mean round time as records per second.

    pytest-benchmark's table only shows time per round; this saves the derived rate in the run's
    JSON (``extra_info["records_per_second"]``) and in the summary ``pytest_terminal_summary``
    prints after the table. Does nothing under ``--benchmark-disable``, which records no stats.
    """
    if benchmark.stats is None:
        return
    # The mean round time, as pytest-benchmark's Mean column (its ``mean`` property is untyped).
    rate = records_per_round / statistics.fmean(benchmark.stats.stats.data)
    benchmark.extra_info["records_per_second"] = round(rate)
    request.config.stash.setdefault(THROUGHPUT_KEY, []).append((request.node.nodeid, rate))


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter, config: pytest.Config) -> None:
    results = config.stash.get(THROUGHPUT_KEY, [])
    if not results:
        return
    terminalreporter.section("throughput")
    for nodeid, rate in results:
        terminalreporter.write_line(f"{nodeid}: {rate:,.0f} records/sec")
