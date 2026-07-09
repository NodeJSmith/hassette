"""Unit tests for the Tier 1 loop-responsiveness watchdog.

Covers:
    - blocking handler trips exactly one warning naming the app, duration ≈ T
    - await asyncio.sleep(T) trips ZERO warnings (responsiveness-based, not wall-clock)
    - default config never raises; ERROR escalates only via filterwarnings("error")
    - double start is no-op; stop leaves no thread alive; re-start works
    - no loop.set_debug anywhere in the watchdog path

Each async test that does a real time.sleep pins its own function-scoped loop so a
synchronous freeze does not starve the session-scoped loop and trip neighbouring tests.
"""

import asyncio
import inspect
import re
import threading
import time
import warnings
from typing import cast
from unittest.mock import MagicMock

import pytest

from hassette.core import loop_watchdog as loop_watchdog_module
from hassette.core.command_executor import ExecutionMarker
from hassette.core.loop_watchdog import LoopWatchdog, WatchdogEvent
from hassette.exceptions import HassetteBlockingIOWarning
from hassette.types.enums import BlockingIOBehavior

_LAG = 0.10  # threshold: 100ms
_INTERVAL = 0.25  # watchdog_interval_seconds: 250ms (check_interval = /3 ≈ 83ms)
_BLOCK = 0.55  # sync-sleep duration > threshold — reliably triggers detection


def make_hassette(*, behavior: BlockingIOBehavior | None = None) -> MagicMock:
    """Build a minimal mock Hassette with blocking_io config.

    resolve_blocking_io_behavior reads through owner.app_config.blocking_io_behavior
    (per-app) then owner.hassette.config.blocking_io.behavior (global). When the
    watchdog calls _emit with no live app instance (app_handler.get returns None),
    owner is self._hassette. So the resolver checks:
      1. self._hassette.app_config.blocking_io_behavior — must be None to fall through
      2. self._hassette.hassette.config.blocking_io.behavior — the global path

    We set app_config.blocking_io_behavior = None explicitly to force the global path.
    """
    cfg = MagicMock()
    cfg.blocking_io.watchdog_enabled = True
    cfg.blocking_io.lag_threshold_seconds = _LAG
    cfg.blocking_io.watchdog_interval_seconds = _INTERVAL
    cfg.blocking_io.capture_stack_on_block = False  # skip stack for unit tests
    cfg.blocking_io.behavior = behavior
    h = MagicMock()
    h.config = cfg
    # app_handler.get returns None → watchdog uses h as owner for behavior resolution.
    h.app_handler.get.return_value = None
    # Force per-app path to None so resolver falls through to global config.
    h.app_config.blocking_io_behavior = None
    # Wire the global path: h.hassette.config.blocking_io.behavior = behavior
    h.hassette.config.blocking_io.behavior = behavior
    return h


def make_executor(app_key: str | None = "test_app") -> MagicMock:
    """Build a mock executor with a controllable current_execution marker.

    Stamps the marker with the current task id so the watchdog's task-identity confirmation
    treats a block in *this* task as attributed (the blocking-in-own-task case these tests model).
    """
    executor = MagicMock()
    task = asyncio.current_task()
    executor.current_execution = ExecutionMarker(
        app_key=app_key,
        instance_name=None,
        execution_id="exec-123",
        started_at=time.monotonic(),
        task_id=id(task) if task is not None else None,
    )
    return executor


def make_watchdog(
    loop: asyncio.AbstractEventLoop,
    executor: MagicMock,
    *,
    hassette: MagicMock | None = None,
) -> LoopWatchdog:
    if hassette is None:
        hassette = make_hassette()
    return LoopWatchdog(
        hassette,
        loop=loop,
        loop_thread_id=threading.get_ident(),
        executor=executor,
    )


def test_watchdog_does_not_call_set_debug() -> None:
    """LoopWatchdog must never call loop.set_debug(True)."""
    src = inspect.getsource(loop_watchdog_module)
    assert "set_debug" not in src, "loop_watchdog.py must not reference set_debug"


@pytest.mark.asyncio(loop_scope="function")
async def test_double_start_is_noop() -> None:
    """Starting the watchdog twice is a no-op — second call must not spawn another thread."""
    loop = asyncio.get_running_loop()
    executor = make_executor()
    executor.current_execution = None  # no execution running

    watchdog = make_watchdog(loop, executor)
    try:
        watchdog.start()
        thread_after_first = watchdog._daemon_thread
        watchdog.start()  # second call — must be a no-op
        assert watchdog._daemon_thread is thread_after_first, "double start spawned a second thread"
    finally:
        watchdog.stop()


@pytest.mark.asyncio(loop_scope="function")
async def test_stop_cleans_up_thread_and_handle() -> None:
    """After stop(), no daemon thread is alive and the tick handle is cancelled."""
    loop = asyncio.get_running_loop()
    executor = make_executor()
    executor.current_execution = None

    watchdog = make_watchdog(loop, executor)
    watchdog.start()
    thread = watchdog._daemon_thread
    assert thread is not None
    assert thread.is_alive()

    watchdog.stop()

    assert not thread.is_alive(), "daemon thread outlived stop()"
    assert watchdog._tick_handle is None, "tick handle not cleared after stop()"
    assert watchdog._daemon_thread is None, "daemon thread reference not cleared after stop()"


@pytest.mark.asyncio(loop_scope="function")
async def test_stop_before_start_is_noop() -> None:
    """Calling stop() on an unstarted watchdog must not raise."""
    loop = asyncio.get_running_loop()
    executor = make_executor()
    watchdog = make_watchdog(loop, executor)
    watchdog.stop()  # must not raise


@pytest.mark.asyncio(loop_scope="function")
async def test_restart_after_stop_works() -> None:
    """After stop(), a second start() re-installs cleanly."""
    loop = asyncio.get_running_loop()
    executor = make_executor()
    executor.current_execution = None

    watchdog = make_watchdog(loop, executor)
    watchdog.start()
    watchdog.stop()

    # Second start must succeed and spawn a fresh thread.
    watchdog.start()
    try:
        assert watchdog._daemon_thread is not None
        assert watchdog._daemon_thread.is_alive()
    finally:
        watchdog.stop()


@pytest.mark.asyncio(loop_scope="function")
async def test_blocking_sleep_emits_exactly_one_warning() -> None:
    """A time.sleep > threshold on the loop thread produces exactly ONE warning.

    A real time.sleep is required to produce a genuine tick stall; the function-scoped
    loop keeps that freeze from starving other tests.
    """
    loop = asyncio.get_running_loop()
    executor = make_executor("kitchen_lights")

    # filterwarnings("error") is the global default in this test suite, so
    # pytest.warns must temporarily downgrade back to warning to catch it.
    with pytest.warns(HassetteBlockingIOWarning) as record:
        watchdog = make_watchdog(loop, executor)
        watchdog.start()
        try:
            # Freeze the loop thread — this is the very thing under test.
            time.sleep(_BLOCK)  # noqa: ASYNC251 — intentional loop freeze; this is what we detect
            # The "handler" is done: clear its marker (as unbind_execution_context does in
            # production) before yielding. The daemon already captured this marker during the
            # freeze, so episode 1 still emits — but a CPU-starvation tick lag during recovery
            # (common under heavy CI parallelism) now finds no live execution and opens no second
            # episode, so the one-warning assertion stays true under load.
            executor.current_execution = None
            # Let the watchdog detect and the loop recover.
            await asyncio.sleep(_INTERVAL * 2)
        finally:
            watchdog.stop()

    # Exactly one warning, naming the right app.
    assert len(record) == 1, f"expected 1 warning, got {len(record)}: {[str(w.message) for w in record]}"
    msg = str(record[0].message)
    assert "kitchen_lights" in msg, f"app key not in warning: {msg!r}"
    assert HassetteBlockingIOWarning == record[0].category


@pytest.mark.asyncio(loop_scope="function")
async def test_blocking_sleep_warning_reports_full_duration() -> None:
    """The reported stall duration approximates the full block T, not the detection latency.

    Warn-after means the duration is measured across the whole freeze (tick-starvation span),
    so it must be close to T (~550ms), not the old first-detection value (~threshold ≈ 167ms).
    """
    loop = asyncio.get_running_loop()
    executor = make_executor("my_app")

    with pytest.warns(HassetteBlockingIOWarning) as record:
        watchdog = make_watchdog(loop, executor)
        watchdog.start()
        try:
            time.sleep(_BLOCK)  # noqa: ASYNC251
            await asyncio.sleep(_INTERVAL * 2)
        finally:
            watchdog.stop()

    msg = str(record[0].message)
    match = re.search(r"stall: (\d+)ms", msg)
    assert match is not None, f"no stall duration in warning: {msg!r}"
    reported_ms = int(match.group(1))
    block_ms = _BLOCK * 1000.0
    # Must be close to the real block, not the ~threshold value the old first-detection logic gave.
    # Generous bounds absorb scheduling jitter while still excluding the ~167ms regression.
    assert reported_ms >= block_ms * 0.7, f"duration {reported_ms}ms under-reports block {block_ms:.0f}ms"
    assert reported_ms <= block_ms * 2.0, f"duration {reported_ms}ms over-reports block {block_ms:.0f}ms"


@pytest.mark.asyncio(loop_scope="function")
async def test_async_sleep_produces_no_warning() -> None:
    """await asyncio.sleep(T) for T >> threshold MUST produce zero warnings.

    The central correctness test: the loop stays responsive across an await, so the tick
    keeps advancing and no stall is ever detected.

    Detection is gated on tick staleness, not marker age. While the handler
    awaits, the loop is free and the tick advances normally — so no stall is
    ever flagged, even though the execution marker has been set for T seconds.
    """
    loop = asyncio.get_running_loop()
    executor = make_executor("slow_but_fine_app")

    # Give the watchdog a live marker (as if an execution is running) and
    # let it run for more than _BLOCK while the loop stays responsive.
    with warnings.catch_warnings():
        warnings.simplefilter("error", HassetteBlockingIOWarning)
        watchdog = make_watchdog(loop, executor)
        watchdog.start()
        try:
            # This must not raise — the loop is free throughout.
            await asyncio.sleep(_BLOCK + _INTERVAL)
        finally:
            watchdog.stop()
    # If we reach here without an exception, zero warnings were emitted. ✓


@pytest.mark.asyncio(loop_scope="function")
async def test_default_config_emits_warning_not_exception() -> None:
    """Under default config (WARN), a stall emits a warning — never an unconditional raise."""
    loop = asyncio.get_running_loop()
    executor = make_executor("any_app")

    # Temporarily suppress the global "error" filter so we can catch the plain warning.
    with pytest.warns(HassetteBlockingIOWarning):
        watchdog = make_watchdog(loop, executor)
        watchdog.start()
        try:
            time.sleep(_BLOCK)  # noqa: ASYNC251
            await asyncio.sleep(_INTERVAL * 2)
        finally:
            watchdog.stop()
    # Reaching here means: a warning was emitted but no exception was raised ✓


@pytest.mark.asyncio(loop_scope="function")
async def test_error_behavior_emits_via_warnings_not_unconditional_raise() -> None:
    """ERROR behavior still routes through warnings.warn; the watchdog never raises itself.

    ERROR differs from IGNORE (it emits) but not from WARN at the watchdog: both call
    warnings.warn. Escalation to an exception is the user's filterwarnings("error"), applied by
    the warnings machinery — not an unconditional raise from the watchdog. The warning is emitted
    from the daemon thread, so it cannot propagate into this coroutine; we assert it is emitted.
    """
    loop = asyncio.get_running_loop()
    executor = make_executor("strict_app")
    hassette = make_hassette(behavior=BlockingIOBehavior.ERROR)

    with pytest.warns(HassetteBlockingIOWarning):
        watchdog = make_watchdog(loop, executor, hassette=hassette)
        watchdog.start()
        try:
            time.sleep(_BLOCK)  # noqa: ASYNC251
            await asyncio.sleep(_INTERVAL * 2)
        finally:
            watchdog.stop()


@pytest.mark.asyncio(loop_scope="function")
async def test_on_stall_fires_before_warning_and_survives_escalation() -> None:
    """on_stall (persist) is called before warnings.warn, so a filterwarnings('error') escalation
    neither skips persistence nor kills the daemon thread.

    Regression: previously _emit warned before calling on_stall, so an escalated warning raised on
    the daemon thread skipped the persist AND killed the watchdog.
    """
    loop = asyncio.get_running_loop()
    executor = make_executor("persist_app")
    on_stall = MagicMock()
    hassette = make_hassette()

    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=HassetteBlockingIOWarning)
        watchdog = LoopWatchdog(
            hassette,
            loop=loop,
            loop_thread_id=threading.get_ident(),
            executor=executor,
            on_stall=on_stall,
        )
        watchdog.start()
        try:
            time.sleep(_BLOCK)  # noqa: ASYNC251
            # Handler done — clear the marker so a CPU-starvation tick lag during recovery opens
            # no second episode (which would call on_stall twice and fail assert_called_once).
            executor.current_execution = None
            await asyncio.sleep(_INTERVAL * 2)
            # The daemon must still be alive after the escalated warning (not killed).
            assert watchdog._daemon_thread is not None
            assert watchdog._daemon_thread.is_alive()
        finally:
            watchdog.stop()

    on_stall.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_ignore_behavior_suppresses_warning() -> None:
    """BlockingIOBehavior.IGNORE suppresses warning entirely."""
    loop = asyncio.get_running_loop()
    executor = make_executor("ignored_app")

    # Build a hassette mock whose resolve_blocking_io_behavior returns IGNORE.
    # The simplest way: set the global blocking_io.behavior to IGNORE.
    hassette = make_hassette(behavior=BlockingIOBehavior.IGNORE)
    # Also mock the config accessor path used by resolve_blocking_io_behavior.
    hassette.config.blocking_io.behavior = BlockingIOBehavior.IGNORE

    with warnings.catch_warnings():
        warnings.simplefilter("error", HassetteBlockingIOWarning)
        watchdog = make_watchdog(loop, executor, hassette=hassette)
        watchdog.start()
        try:
            time.sleep(_BLOCK)  # noqa: ASYNC251
            await asyncio.sleep(_INTERVAL * 2)
        finally:
            watchdog.stop()
    # No exception raised → IGNORE suppressed the warning ✓


@pytest.mark.asyncio(loop_scope="function")
async def test_deduplication_one_warning_per_stall_episode() -> None:
    """A single stall episode spanning multiple daemon polls emits exactly ONE warning."""
    loop = asyncio.get_running_loop()
    executor = make_executor("dedup_app")

    with pytest.warns(HassetteBlockingIOWarning) as record:
        watchdog = make_watchdog(loop, executor)
        watchdog.start()
        try:
            # Sleep long enough that the daemon polls several times (> 3 check intervals).
            time.sleep(_BLOCK * 2)  # noqa: ASYNC251
            # Handler done — clear the marker before yielding so a CPU-starvation tick lag during
            # recovery opens no second episode (the daemon captured it during the freeze).
            executor.current_execution = None
            await asyncio.sleep(_INTERVAL * 2)
        finally:
            watchdog.stop()

    assert len(record) == 1, f"expected 1 warning for one stall, got {len(record)}"


def test_watchdog_event_fields() -> None:
    """WatchdogEvent carries all fields needed for blocking_events persistence."""
    event = WatchdogEvent(
        app_key="lights_app",
        instance_name="office",
        instance_index=0,
        execution_id="exec-abc",
        stall_duration_ms=350.0,
        tier="watchdog",
        stack_text=None,
        detected_at=time.time(),
        reason="attributed",
    )
    assert event.tier == "watchdog"
    assert event.app_key == "lights_app"
    assert event.stall_duration_ms == 350.0
    assert event.instance_name == "office"
    assert event.instance_index == 0
    assert event.stack_text is None
    assert event.reason == "attributed"


# Issue #1048 — task-identity confirmation. The single-slot marker names the most-recently-bound
# execution, which under concurrent load is not always the task frozen on the loop. The watchdog
# confirms the marker's task is the one actually frozen and withholds attribution otherwise, so a
# displaced or idle/framework freeze is recorded honestly instead of blaming an innocent app.
@pytest.mark.asyncio(loop_scope="function")
async def test_classify_attribution_distinguishes_outcomes() -> None:
    """Matching task → attributed; different (or absent) task → displaced; no task on the loop
    at all → framework."""
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    assert task is not None
    watchdog = make_watchdog(loop, make_executor())

    attributed = ExecutionMarker("app", None, "e1", time.monotonic(), task_id=id(task))
    assert watchdog._classify_attribution(attributed) == "attributed"

    # The frozen task (this test task) is live but its id does not match the marker's task.
    displaced = ExecutionMarker("app", None, "e2", time.monotonic(), task_id=-1)
    assert watchdog._classify_attribution(displaced) == "displaced"

    no_task = ExecutionMarker("app", None, "e3", time.monotonic(), task_id=None)
    assert watchdog._classify_attribution(no_task) == "displaced"

    # A loop with no running task (e.g. idle in select()) reads current_task() as None → framework.
    # asyncio.current_task(loop) is a plain _current_tasks dict lookup, so a sentinel loop that was
    # never run resolves to None — no real loop needed (and nothing to leak).
    idle_loop = cast("asyncio.AbstractEventLoop", object())
    idle_watchdog = make_watchdog(idle_loop, make_executor())
    assert idle_watchdog._classify_attribution(attributed) == "framework"


@pytest.mark.asyncio(loop_scope="function")
async def test_displaced_block_not_attributed_to_innocent_app() -> None:
    """A freeze whose marker was bound by a different task records NULL + reason='displaced',
    and the warning labels it <framework> rather than blaming the marker's app."""
    loop = asyncio.get_running_loop()
    executor = MagicMock()
    # Marker bound by a different task than the one that will freeze the loop. id() is never
    # negative, so task_id=-1 can never match the frozen task and reliably models displacement.
    executor.current_execution = ExecutionMarker(
        app_key="innocent_app",
        instance_name=None,
        execution_id="exec-displaced",
        started_at=time.monotonic(),
        task_id=-1,
    )
    captured: list[WatchdogEvent] = []

    with pytest.warns(HassetteBlockingIOWarning) as record:
        watchdog = LoopWatchdog(
            make_hassette(),
            loop=loop,
            loop_thread_id=threading.get_ident(),
            executor=executor,
            on_stall=captured.append,
        )
        watchdog.start()
        try:
            time.sleep(_BLOCK)  # noqa: ASYNC251 — intentional loop freeze; this is what we detect
            executor.current_execution = None
            await asyncio.sleep(_INTERVAL * 2)
        finally:
            watchdog.stop()

    msg = str(record[0].message)
    assert "innocent_app" not in msg
    assert "<framework>" in msg
    assert captured, "on_stall should record the displaced stall"
    assert captured[0].app_key is None
    assert captured[0].execution_id is None
    assert captured[0].reason == "displaced"


@pytest.mark.asyncio(loop_scope="function")
async def test_attributed_block_records_reason_attributed() -> None:
    """A freeze whose marker matches the frozen task is attributed to its app, reason='attributed'."""
    loop = asyncio.get_running_loop()
    executor = make_executor("kitchen_lights")  # task_id stamped with this task
    captured: list[WatchdogEvent] = []

    with pytest.warns(HassetteBlockingIOWarning):
        watchdog = LoopWatchdog(
            make_hassette(),
            loop=loop,
            loop_thread_id=threading.get_ident(),
            executor=executor,
            on_stall=captured.append,
        )
        watchdog.start()
        try:
            time.sleep(_BLOCK)  # noqa: ASYNC251 — intentional loop freeze; this is what we detect
            executor.current_execution = None
            await asyncio.sleep(_INTERVAL * 2)
        finally:
            watchdog.stop()

    assert captured
    assert captured[0].app_key == "kitchen_lights"
    assert captured[0].reason == "attributed"
    assert captured[0].execution_id == "exec-123"
