"""Scheduler job-queue hot-path timings at 100, 1,000 and 10,000 queued jobs.

Each round starts from a freshly built queue of ``size`` jobs (built in pytest-benchmark's
untimed ``setup``), so an operation that mutates the heap never skews the next round.
"""

import functools

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from hassette.scheduler.classes import Job
from tests.support.factories import make_scheduled_job

from .conftest import QUEUE_SIZES, RunAsync, make_job_queue, make_queue_jobs

ROUNDS = 50
"""Timed rounds per case; setup rebuilds the heap each round, which dominates wall time at 10,000 jobs."""


@functools.cache
def queue_jobs(size: int) -> list[Job]:
    """Jobs for a queue of ``size``, built once per size and shared by every round."""
    return make_queue_jobs(size)


@pytest.mark.parametrize("size", QUEUE_SIZES)
def test_add(benchmark: BenchmarkFixture, run_async: RunAsync, size: int) -> None:
    """Push one more job onto a queue already holding ``size`` jobs."""
    jobs = queue_jobs(size)
    new_job = make_scheduled_job(name="bench_new_job", next_run=jobs[size // 2].next_run)

    def setup():
        return (make_job_queue(jobs),), {}

    def add(queue):
        run_async(queue.add(new_job))

    benchmark.pedantic(add, setup=setup, rounds=ROUNDS, iterations=1)


@pytest.mark.parametrize("size", QUEUE_SIZES)
def test_pop_due_and_peek_next(benchmark: BenchmarkFixture, run_async: RunAsync, size: int) -> None:
    """Pop the single due job and peek the next fire time from a queue of ``size`` jobs."""
    jobs = queue_jobs(size)
    reference_time = jobs[0].fire_at
    assert reference_time is not None

    def setup():
        return (make_job_queue(jobs),), {}

    def pop_due_and_peek_next(queue):
        due, _ = run_async(queue.pop_due_and_peek_next(reference_time))
        assert len(due) == 1

    benchmark.pedantic(pop_due_and_peek_next, setup=setup, rounds=ROUNDS, iterations=1)


@pytest.mark.parametrize("size", QUEUE_SIZES)
def test_remove_job(benchmark: BenchmarkFixture, run_async: RunAsync, size: int) -> None:
    """Remove a job from the middle of a queue of ``size`` jobs.

    The queue has no reschedule operation; rescheduling a job is a ``remove_job`` followed by an
    ``add``, so this case and ``test_add`` together cover it.
    """
    jobs = queue_jobs(size)
    target = jobs[size // 2]

    def setup():
        return (make_job_queue(jobs),), {}

    def remove_job(queue):
        assert run_async(queue.remove_job(target))

    benchmark.pedantic(remove_job, setup=setup, rounds=ROUNDS, iterations=1)
