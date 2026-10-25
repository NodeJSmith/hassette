"""PipelineCounters: closed counter enum and a thread-safe process-wide registry."""

import threading
from pathlib import Path

from hassette.core.core import Hassette
from hassette.core.pipeline_counters import CounterKind, PipelineCounter, PipelineCounters
from hassette.testing.config import make_test_config

THREAD_COUNT = 8
INCREMENTS_PER_THREAD = 5_000


def test_every_member_has_stage_reason_and_kind() -> None:
    """Each member carries a non-empty stage and reason and a CounterKind."""
    for counter in PipelineCounter:
        assert counter.stage
        assert counter.reason
        assert isinstance(counter.kind, CounterKind)


def test_stage_reason_pairs_are_unique() -> None:
    """No two members share a (stage, reason) pair."""
    pairs = [(c.stage, c.reason) for c in PipelineCounter]
    assert len(pairs) == len(set(pairs))


def test_non_loss_kinds() -> None:
    """Only the framework-sample filter counts as sampled and only the error handler as a failure."""
    assert PipelineCounter.EXECUTION_FILTER_FRAMEWORK_SAMPLED.kind is CounterKind.SAMPLED
    assert PipelineCounter.ERROR_HANDLER_HANDLER_RAISED.kind is CounterKind.FAILURE
    others = set(PipelineCounter) - {
        PipelineCounter.EXECUTION_FILTER_FRAMEWORK_SAMPLED,
        PipelineCounter.ERROR_HANDLER_HANDLER_RAISED,
    }
    assert all(c.kind is CounterKind.LOSS for c in others)


def test_counts_start_at_zero() -> None:
    """A fresh registry reports zero for every member."""
    counters = PipelineCounters()
    assert counters.snapshot() == dict.fromkeys(PipelineCounter, 0)


def test_increment_and_get() -> None:
    """Increment adds 1 by default or n when given, and only to the named counter."""
    counters = PipelineCounters()
    counters.increment(PipelineCounter.LOG_QUEUE_OVERFLOW)
    counters.increment(PipelineCounter.LOG_QUEUE_OVERFLOW, n=4)

    assert counters.get(PipelineCounter.LOG_QUEUE_OVERFLOW) == 5
    assert counters.get(PipelineCounter.EXECUTION_WRITE_SHUTDOWN) == 0


def test_snapshot_is_a_copy() -> None:
    """Mutating a snapshot or incrementing after it does not change the other."""
    counters = PipelineCounters()
    counters.increment(PipelineCounter.WS_BROADCAST_CLIENT_QUEUE_FULL, n=2)

    snap = counters.snapshot()
    snap[PipelineCounter.WS_BROADCAST_CLIENT_QUEUE_FULL] = 99
    counters.increment(PipelineCounter.WS_BROADCAST_CLIENT_QUEUE_FULL)

    assert counters.get(PipelineCounter.WS_BROADCAST_CLIENT_QUEUE_FULL) == 3
    assert counters.snapshot()[PipelineCounter.WS_BROADCAST_CLIENT_QUEUE_FULL] == 3


def test_concurrent_increments_sum_correctly() -> None:
    """Increments from several threads at once are never lost."""
    counters = PipelineCounters()
    barrier = threading.Barrier(THREAD_COUNT)

    def worker() -> None:
        barrier.wait()
        for _ in range(INCREMENTS_PER_THREAD):
            counters.increment(PipelineCounter.LOG_DB_WRITE_QUEUE_OVERFLOW)

    threads = [threading.Thread(target=worker) for _ in range(THREAD_COUNT)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counters.get(PipelineCounter.LOG_DB_WRITE_QUEUE_OVERFLOW) == THREAD_COUNT * INCREMENTS_PER_THREAD


def test_hassette_owns_a_registry_from_construction(tmp_path: Path) -> None:
    """Hassette sets pipeline_counters in __init__, before wire_services()."""
    hassette = Hassette(make_test_config(data_dir=tmp_path))
    assert isinstance(hassette.pipeline_counters, PipelineCounters)
