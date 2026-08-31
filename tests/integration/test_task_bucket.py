import asyncio
import concurrent.futures
import contextlib
import inspect
from unittest.mock import patch

import pytest

from hassette import context as ctx
from hassette.task_bucket import TaskBucket


async def sleeper():
    try:
        await asyncio.sleep(10)  # long sleep; will be cancelled
    except asyncio.CancelledError:
        # simulate well-behaved cleanup
        await asyncio.sleep(0)
        raise


async def test_cancel_all_cancels_cooperative_tasks(bucket: TaskBucket):
    """cancel_all cooperatively stops tracked tasks."""
    cooperative_task = asyncio.create_task(sleeper(), name="cooperative")
    # factory should auto-register; no explicit bucket.add/spawn needed
    await asyncio.sleep(0)  # let it start

    assert len(bucket) >= 1, f"bucket should track at least one task, tracks {len(bucket)}"

    await bucket.cancel_all()

    loop = asyncio.get_running_loop()
    current_time = loop.time()
    cancellation_deadline = current_time + bucket.config_cancel_timeout + 0.5
    while not cooperative_task.done() and current_time < cancellation_deadline:
        await asyncio.sleep(0.01)
        current_time = loop.time()

    assert cooperative_task.done(), f"task should be done after cancel_all, is {cooperative_task._state}"
    assert cooperative_task.cancelled(), "task should be cancelled after cancel_all"


async def boom(event: asyncio.Event):
    await asyncio.sleep(0)
    event.set()
    raise RuntimeError("boom")


async def test_crash_invokes_exception_recorder(bucket: TaskBucket):
    """Task crashes are observed via the exception recorder callback."""
    task_started = asyncio.Event()
    recorded: list[tuple[asyncio.Task, BaseException]] = []

    def recorder(t: asyncio.Task, exc: BaseException) -> None:
        recorded.append((t, exc))

    bucket.install_exception_recorder(recorder)

    try:
        crashing_task = asyncio.create_task(boom(task_started), name="exploder")
        await task_started.wait()
        await asyncio.sleep(0)  # let done callbacks fire

        assert crashing_task.done()
        assert not crashing_task.cancelled()
        assert len(recorded) == 1
        assert recorded[0][0] is crashing_task
        assert isinstance(recorded[0][1], RuntimeError)
    finally:
        bucket.uninstall_exception_recorder(recorder)


async def stubborn(event: asyncio.Event):
    loop = asyncio.get_running_loop()
    end = loop.time() + 1  # longer than bucket timeout
    while loop.time() < end:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(0.01)
    event.set()


async def test_stubborn_task_survives_cancel_all(bucket: TaskBucket):
    """Tasks that ignore cancellation finish on their own terms after cancel_all."""
    stubborn_task_finished = asyncio.Event()
    stubborn_task_handle = asyncio.create_task(stubborn(stubborn_task_finished), name="stubborn")

    assert len(bucket) >= 1, f"bucket should track at least one task, tracks {len(bucket)}"

    await asyncio.sleep(0)

    await bucket.cancel_all()
    await stubborn_task_finished.wait()
    await asyncio.sleep(0)

    assert stubborn_task_handle.done()
    assert not stubborn_task_handle.cancelled()


async def test_factory_tracks_rogue_create_task(bucket: TaskBucket):
    """Task factory picks up plain asyncio.create_task usage."""
    rogue_task_started = asyncio.Event()

    async def rogue():
        bucket.post_to_loop(rogue_task_started.set)
        await asyncio.sleep(10)

    rogue_task_handle = asyncio.create_task(rogue(), name="rogue")
    await asyncio.sleep(0)
    await rogue_task_started.wait()
    # No direct bucket.add; rely on factory
    assert len(bucket) >= 1, f"bucket should track at least one task, tracks {len(bucket)}"

    await bucket.cancel_all()
    assert rogue_task_handle.done(), f"task should be done after cancel_all, is {rogue_task_handle._state}"
    assert rogue_task_handle.cancelled(), "task should be cancelled after cancel_all"


async def test_protect_task_does_not_hide_explicit_spawn_from_its_own_bucket(bucket: TaskBucket):
    """PROTECT_TASK must not blind a bucket to work explicitly spawned on it.

    Regression test: the task factory used to check PROTECT_TASK before CURRENT_BUCKET, so a
    protected context (e.g. the test-harness ``watcher`` fixture in test_service_watcher.py)
    made every task invisible to tracking -- including ones created via the bucket's own
    ``spawn()``, which explicitly claims CURRENT_BUCKET for the duration. That left
    explicitly-owned work untracked and uncancellable by its own bucket's cancel_all().
    PROTECT_TASK should only suppress tracking for *unclaimed* tasks that would otherwise fall
    through to the global fallback bucket -- not tasks a bucket explicitly claimed.
    """
    ctx.PROTECT_TASK.set(True)
    try:
        spawned = bucket.spawn(sleeper(), name="protected-context-explicit-spawn")
        await asyncio.sleep(0)  # let it start

        assert spawned in bucket.pending_tasks(), (
            "bucket.spawn() must still be tracked by its own bucket under PROTECT_TASK"
        )

        await bucket.cancel_all()
        assert spawned.done(), f"task should be done after cancel_all, is {spawned._state}"
        assert spawned.cancelled(), "task should be cancelled after cancel_all"
    finally:
        ctx.PROTECT_TASK.set(False)


async def test_run_sync_raises_inside_loop(bucket: TaskBucket) -> None:
    """run_sync rejects being invoked inside the running event loop."""

    async def sample_coroutine():
        return 42

    with pytest.raises(RuntimeError):
        bucket.run_sync(sample_coroutine())


async def test_run_sync_drives_coroutine_from_worker_thread(bucket: TaskBucket) -> None:
    """run_sync bridges a coroutine from a worker thread onto the running loop and returns its result.

    This is the path every sync facade (api/bus/scheduler/entity) depends on: a sync caller
    off the loop thread drives an async method to completion via run_coroutine_threadsafe.
    Calling through asyncio.to_thread is what makes the run_sync loop-guard pass instead of raise.
    """

    async def add(a: int, b: int) -> int:
        await asyncio.sleep(0)
        return a + b

    result = await asyncio.to_thread(bucket.run_sync, add(2, 3))
    assert result == 5


async def test_seal_rejects_spawn_and_closes_unsubmitted_coroutine(bucket: TaskBucket):
    """A sealed bucket refuses spawn(), closing the coroutine instead of leaking a task."""

    async def never_runs():
        await asyncio.sleep(10)

    coro = never_runs()
    bucket.seal()
    try:
        with pytest.raises(RuntimeError, match=bucket.unique_name):
            bucket.spawn(coro, name="rejected")

        assert inspect.getcoroutinestate(coro) == "CORO_CLOSED", "rejected coroutine must be closed, not leaked"
    finally:
        bucket.reopen()


async def test_seal_rejects_task_factory_add_and_cancels_task(bucket: TaskBucket):
    """A sealed bucket rejects tasks created via the loop's task factory too.

    asyncio.create_task() (not bucket.spawn()) routes through make_task_factory's
    factory function, which calls TaskBucket.add() directly on the current-context
    bucket. Sealing must reject there as well: the already-created task is cancelled,
    never tracked, and its eventual exception (cancellation or otherwise) is consumed
    so rejection cannot leak an unobserved-task-exception warning.
    """

    async def rogue():
        await asyncio.sleep(10)

    # The task factory constructs the task before add() can reject and cancel it, and
    # create_task() never returns a handle once add() raises — so the only reliable way to
    # keep a reference is to capture it as add() is called, rather than trying to recover it
    # afterward by filtering asyncio.all_tasks().
    #
    # No name assertion here on purpose: on Python <3.14, asyncio.BaseEventLoop.create_task()
    # applies a caller-supplied name=... to the returned task via tasks._set_task_name() *after*
    # the task factory returns (only 3.14 forwards name= directly into the factory's own
    # kwargs — see make_task_factory()'s docstring). Since a rejected task's factory call never
    # returns, that post-hoc rename never runs, so the task's name at rejection time is still the
    # coroutine's fallback name ("rogue"), not "rejected-rogue" — confirmed by reproducing this
    # exact mismatch locally on 3.11. Identity (there is exactly one captured task, and it's the
    # one this test created) is what the assertions below actually need, not its name.
    captured_tasks: list[asyncio.Task] = []
    original_add = bucket.add

    def spy_add(task: asyncio.Task) -> None:
        captured_tasks.append(task)
        original_add(task)

    bucket.seal()
    try:
        with (
            patch.object(bucket, "add", side_effect=spy_add),
            ctx.use_task_bucket(bucket),
            pytest.raises(RuntimeError, match=bucket.unique_name),
        ):
            asyncio.create_task(rogue(), name="rejected-rogue")  # noqa: RUF006

        assert len(captured_tasks) == 1, "add() must be called exactly once with the rejected task"
        rejected_task = captured_tasks[0]

        with contextlib.suppress(asyncio.CancelledError):
            await rejected_task

        assert rejected_task.cancelled()
        assert rejected_task not in bucket.pending_tasks(), "rejected task must never be tracked by the bucket"
    finally:
        bucket.reopen()


async def test_reopen_after_seal_allows_new_work(bucket: TaskBucket):
    """reopen() clears sealing so spawn() succeeds again."""
    bucket.seal()
    assert bucket.is_sealed

    async def blocked():
        raise AssertionError("must never run while sealed")

    with pytest.raises(RuntimeError, match=bucket.unique_name):
        bucket.spawn(blocked(), name="blocked-while-sealed")

    bucket.reopen()
    assert not bucket.is_sealed

    gate = asyncio.Event()

    async def allowed():
        await gate.wait()

    task = bucket.spawn(allowed(), name="allowed-after-reopen")
    assert task in bucket.pending_tasks()

    gate.set()
    await task


async def test_pending_task_names_returns_sorted_deterministic_snapshot(bucket: TaskBucket):
    """pending_task_names() is a synchronous, sorted snapshot of pending task names."""
    gate = asyncio.Event()

    async def sleeper():
        await gate.wait()

    task_b = bucket.spawn(sleeper(), name="evidence-task-b")
    task_a = bucket.spawn(sleeper(), name="evidence-task-a")

    names = bucket.pending_task_names()
    assert "evidence-task-a" in names
    assert "evidence-task-b" in names
    assert names == tuple(sorted(names)), "names must come back in deterministic sorted order"

    gate.set()
    await asyncio.gather(task_a, task_b)

    assert "evidence-task-a" not in bucket.pending_task_names()
    assert "evidence-task-b" not in bucket.pending_task_names()


async def test_cancel_all_returns_names_still_pending(bucket: TaskBucket):
    """cancel_all() returns the deterministic names of tasks still pending after its bounded wait."""
    stubborn_finished = asyncio.Event()
    stubborn_task = asyncio.create_task(stubborn(stubborn_finished), name="stubborn-evidence")

    await asyncio.sleep(0)

    pending_names = await bucket.cancel_all()

    assert pending_names == ("stubborn-evidence",)

    await stubborn_finished.wait()
    await asyncio.sleep(0)
    assert stubborn_task.done()


async def test_run_sync_timeout_zero_fails_immediately(bucket: TaskBucket) -> None:
    """timeout_seconds=0 fails immediately instead of falling back to the config default.

    Guards the ``if timeout_seconds is None`` semantics: an explicit 0 is a real value, not
    ``None``, so it must not be replaced by the (non-zero) configured default.
    """

    async def never_returns() -> None:
        await asyncio.sleep(100)

    with pytest.raises(concurrent.futures.TimeoutError):
        await asyncio.to_thread(bucket.run_sync, never_returns(), timeout_seconds=0)
