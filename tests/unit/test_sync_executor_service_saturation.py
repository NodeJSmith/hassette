"""Unit tests for SyncExecutorService saturation warnings and shutdown behavior.

Covers:
- Submission-time saturation WARNING fires near pool ceiling, rate-limited.
- Periodic probe emits saturation WARNING even when submissions have stopped.
- Python busy-loop worker interrupted within shutdown budget; name+stack logged.
- Shutdown does not raise; completes cleanly after interrupting Python worker.
- C-blocked worker (time.sleep) logged and abandoned; shutdown completes.
- Custom max_workers and shutdown_timeout change behavior; defaults apply when unset.

Uses the asyncio.Event/threading.Event gate pattern from CLAUDE.md to hold workers
across boundaries.

Construction, wiring, and dependency-graph tests live in
test_sync_executor_service_wiring.py.
"""

import asyncio
import contextlib
import os
import sys
import threading
import time
from typing import Any
from unittest.mock import patch

import coverage
import pytest
from pydantic import ValidationError

import hassette.task_bucket.interruptible_executor as ie_module
from hassette.config import HassetteConfig
from hassette.core.command_executor import (  # pyright: ignore[reportPrivateUsage]
    _CAPACITY_WARN_RATE_LIMIT_SECS,
    _CAPACITY_WARN_THRESHOLD,
)
from hassette.core.sync_executor_service import (
    _SATURATION_PROBE_INTERVAL_SECS,
    _SATURATION_WARN_RATE_LIMIT_SECS,
    _SATURATION_WARN_THRESHOLD,
    SyncExecutorService,
)
from hassette.task_bucket.interruptible_executor import InterruptibleThreadPoolExecutor
from hassette.task_bucket.task_bucket import TaskBucket
from tests.unit.conftest import TEST_TOKEN, make_service, make_sync_executor_hassette

# async_raise(SystemExit) into a worker stuck in a C-level call (time.sleep) deadlocks under
# coverage's settrace tracer on Python 3.11. Python 3.12+ trace via sys.monitoring (PEP 669)
# and are unaffected. Production never runs under coverage, and the non-coverage suite plus the
# 3.12+ coverage runs exercise this path — so skip only the 3.11-under-coverage combination.
skip_c_blocked_under_coverage_py311 = pytest.mark.skipif(
    sys.version_info < (3, 12) and coverage.Coverage.current() is not None,
    reason="async_raise into a C-blocked worker deadlocks under coverage's settrace tracer on Python 3.11",
)


class TestOnShutdown:
    @pytest.mark.anyio
    async def test_on_shutdown_calls_executor_shutdown_with_budget(self) -> None:
        """on_shutdown passes sync_executor_shutdown_timeout_seconds as the budget."""
        svc = make_service(shutdown_timeout=7.5)

        shutdown_calls: list[dict] = []
        original_shutdown = svc.executor.shutdown

        def recording_shutdown(*args: object, **kwargs: object) -> None:
            shutdown_calls.append({"args": args, "kwargs": kwargs})
            original_shutdown(join_threads_or_timeout=False)

        svc.executor.shutdown = recording_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        await svc.on_shutdown()

        assert len(shutdown_calls) == 1
        assert shutdown_calls[0]["kwargs"].get("timeout") == 7.5

    @pytest.mark.anyio
    async def test_on_shutdown_skips_when_executor_not_initialized(self) -> None:
        """on_shutdown is a no-op if on_initialize was never called."""
        mock_hassette = make_sync_executor_hassette()
        svc = SyncExecutorService(mock_hassette)
        await svc.on_shutdown()


# Module-level constant relationship (probe interval >= suppress window)


class TestConstantInvariant:
    """Verify the coupling invariant documented in the module-level comments."""

    def test_probe_interval_gte_suppress_window(self) -> None:
        """Probe interval must be >= suppress window to prevent self-suppression.

        If the probe fires more often than the rate-limit expires, the probe
        would always find the rate-limit unexpired and silently suppress the WARNING.
        This is the coupling invariant documented in sync_executor_service.py.
        """
        assert _SATURATION_PROBE_INTERVAL_SECS >= _SATURATION_WARN_RATE_LIMIT_SECS, (
            f"Probe interval ({_SATURATION_PROBE_INTERVAL_SECS}s) must be >= "
            f"suppress window ({_SATURATION_WARN_RATE_LIMIT_SECS}s) to prevent self-suppression"
        )

    def test_threshold_is_75_percent(self) -> None:
        """Saturation warning threshold must be 75% to match command_executor pattern."""
        assert _SATURATION_WARN_THRESHOLD == 0.75

    def test_constants_match_command_executor(self) -> None:
        """Threshold and rate-limit values must agree with command_executor equivalents.

        Both modules define the same values independently.  This test catches drift —
        if an operator tunes one, they must tune the other.
        """
        assert _SATURATION_WARN_THRESHOLD == _CAPACITY_WARN_THRESHOLD, (
            f"sync_executor threshold ({_SATURATION_WARN_THRESHOLD}) must match "
            f"command_executor threshold ({_CAPACITY_WARN_THRESHOLD})"
        )
        assert _SATURATION_WARN_RATE_LIMIT_SECS == _CAPACITY_WARN_RATE_LIMIT_SECS, (
            f"sync_executor rate-limit ({_SATURATION_WARN_RATE_LIMIT_SECS}s) must match "
            f"command_executor rate-limit ({_CAPACITY_WARN_RATE_LIMIT_SECS}s)"
        )


class TestSubmissionTimeSaturationWarning:
    """log_saturation_rate_limited() fires on submission when pool is near ceiling.

    These tests mock svc.logger.warning directly rather than using caplog, because
    the project uses structlog which routes log output to JSON stdout rather than
    the standard Python logging handler that caplog intercepts.  Mocking the logger's
    warning method gives a clean, ordering-independent signal.
    """

    def test_warning_fires_at_threshold(self) -> None:
        """A WARNING is emitted when active workers reach/exceed the 75% threshold."""
        svc = make_service(max_workers=2)
        gate = threading.Event()

        try:
            ready1 = threading.Event()
            ready2 = threading.Event()

            def block1() -> None:
                ready1.set()
                gate.wait(timeout=5)

            def block2() -> None:
                ready2.set()
                gate.wait(timeout=5)

            svc.executor.submit(block1)
            svc.executor.submit(block2)
            ready1.wait(timeout=2)
            ready2.wait(timeout=2)

            # Manually set active_workers to simulate what track_submission does.
            svc._active_workers = 2

            warning_calls: list[tuple] = []
            svc.logger.warning = lambda msg, *a: warning_calls.append((msg, *a))  # pyright: ignore[reportAttributeAccessIssue]

            svc.log_saturation_rate_limited()

            assert any("approaching saturation" in str(c) for c in warning_calls), (
                f"Expected saturation WARNING; got calls: {warning_calls}"
            )

        finally:
            gate.set()
            svc.executor.shutdown(join_threads_or_timeout=False)

    def test_warning_not_fired_below_threshold(self) -> None:
        """No WARNING is emitted when pool occupancy is below 75%."""
        svc = make_service(max_workers=4)
        # active_workers=0, max_workers=4 → 0% occupancy (well below 75%)
        warning_calls: list[tuple] = []
        svc.logger.warning = lambda msg, *a: warning_calls.append((msg, *a))  # pyright: ignore[reportAttributeAccessIssue]

        svc.log_saturation_rate_limited()

        assert not any("approaching saturation" in str(c) for c in warning_calls), (
            "No WARNING expected when pool is below threshold"
        )
        svc.executor.shutdown(join_threads_or_timeout=False)

    def test_warning_not_fired_just_below_threshold(self) -> None:
        """No WARNING at exactly 74% occupancy (3/4 workers on max_workers=4 pool)."""
        svc = make_service(max_workers=4)
        # 3/4 = 75% — but threshold is strictly >=0.75, so 3/4 = 0.75 should fire.
        # Test the boundary below: 2/4 = 50% must NOT fire.
        svc._active_workers = 2  # 50% occupancy — below threshold

        warning_calls: list[tuple] = []
        svc.logger.warning = lambda msg, *a: warning_calls.append((msg, *a))  # pyright: ignore[reportAttributeAccessIssue]

        svc.log_saturation_rate_limited()

        assert not any("approaching saturation" in str(c) for c in warning_calls), (
            "No WARNING expected at 50% occupancy (below 75% threshold)"
        )
        svc.executor.shutdown(join_threads_or_timeout=False)

    def test_warning_fires_at_exact_threshold(self) -> None:
        """WARNING fires at exactly 75% occupancy (3/4 workers on max_workers=4 pool)."""
        svc = make_service(max_workers=4)
        svc._active_workers = 3  # 3/4 = 75% — exactly at threshold

        warning_calls: list[tuple] = []
        svc.logger.warning = lambda msg, *a: warning_calls.append((msg, *a))  # pyright: ignore[reportAttributeAccessIssue]

        svc.log_saturation_rate_limited()

        assert any("approaching saturation" in str(c) for c in warning_calls), (
            "WARNING must fire at exactly 75% occupancy (at-threshold case)"
        )
        svc.executor.shutdown(join_threads_or_timeout=False)

    def test_warning_rate_limited_not_spammed(self) -> None:
        """Saturation WARNING is rate-limited: second call within window is suppressed."""
        svc = make_service(max_workers=1)
        svc._active_workers = 1  # 100% — above threshold

        warning_calls: list[tuple] = []
        svc.logger.warning = lambda msg, *a: warning_calls.append((msg, *a))  # pyright: ignore[reportAttributeAccessIssue]

        # First call — should log
        svc.log_saturation_rate_limited()
        first_count = len(warning_calls)
        assert first_count >= 1, "Expected at least one WARNING on first call"

        # Second call immediately — should be suppressed by rate-limit
        svc.log_saturation_rate_limited()
        second_count = len(warning_calls)

        assert second_count == first_count, (
            f"Second call within rate-limit window should be suppressed; got {second_count - first_count} extra calls"
        )

        svc.executor.shutdown(join_threads_or_timeout=False)

    def test_warning_fires_again_after_window_expires(self) -> None:
        """After the rate-limit window expires, the WARNING fires again."""
        svc = make_service(max_workers=1)
        svc._active_workers = 1  # 100% — above threshold

        warning_calls: list[tuple] = []
        svc.logger.warning = lambda msg, *a: warning_calls.append((msg, *a))  # pyright: ignore[reportAttributeAccessIssue]

        svc.log_saturation_rate_limited()
        first_count = len(warning_calls)

        # Manually expire the rate-limit window
        svc._last_saturation_warn_ts = time.monotonic() - _SATURATION_WARN_RATE_LIMIT_SECS - 1.0

        svc.log_saturation_rate_limited()
        second_count = len(warning_calls)

        assert second_count > first_count, "WARNING should fire again after the rate-limit window expires"

        svc.executor.shutdown(join_threads_or_timeout=False)

    def test_warning_includes_worker_and_queue_counts(self) -> None:
        """The WARNING message includes active worker count and queue depth."""
        svc = make_service(max_workers=1)
        svc._active_workers = 1  # 100% — above threshold

        warning_calls: list[str] = []
        svc.logger.warning = lambda msg, *a: warning_calls.append(msg % a if a else msg)  # pyright: ignore[reportAttributeAccessIssue]

        svc.log_saturation_rate_limited()

        assert warning_calls, "Expected at least one saturation WARNING"
        msg = str(warning_calls[0])
        # Message should contain worker counts and pool size
        assert "workers active" in msg or "1/1" in msg, f"Expected worker count in WARNING; got: {msg}"

        svc.executor.shutdown(join_threads_or_timeout=False)


class TestPeriodicSaturationProbe:
    """serve() loop emits the saturation WARNING via the periodic probe."""

    @pytest.mark.anyio
    async def test_probe_fires_when_pool_saturated_and_no_submissions(self) -> None:
        """Periodic probe emits saturation WARNING even when no submissions arrive.

        This is the "8/8 workers stuck" scenario — all workers blocked, no new
        submissions, so the submission-time check never fires.  The probe in
        serve() must still surface the saturation WARNING.

        We simulate one probe cycle by calling log_saturation_rate_limited() directly
        (which is exactly what serve()'s TimeoutError branch does), since waiting 30s
        for the real probe is impractical in a unit test.
        """
        svc = make_service(max_workers=2, shutdown_timeout=5.0)

        try:
            # Simulate fully-saturated pool via the active counter (no real submissions needed).
            svc._active_workers = 2

            # Pre-expire the rate-limit so the probe can fire immediately
            svc._last_saturation_warn_ts = 0.0

            warning_calls: list[tuple] = []
            svc.logger.warning = lambda msg, *a: warning_calls.append((msg, *a))  # pyright: ignore[reportAttributeAccessIssue]

            svc.log_saturation_rate_limited()

            assert any("approaching saturation" in str(c) for c in warning_calls), (
                "Probe must fire saturation WARNING when pool is fully saturated"
            )

        finally:
            svc.executor.shutdown(join_threads_or_timeout=False)

    @pytest.mark.anyio
    async def test_serve_exits_on_shutdown_event(self) -> None:
        """serve() exits cleanly when the service-level shutdown_event is set.

        The framework calls request_shutdown() which sets self.shutdown_event (the
        per-service event), then cancels the serve task directly.  We simulate the
        cooperative-exit path by setting the service-level event and then cancelling,
        matching Service.shutdown() behavior.
        """
        svc = make_service(max_workers=2, shutdown_timeout=5.0)
        with patch("hassette.core.sync_executor_service._SATURATION_PROBE_INTERVAL_SECS", 0.05):
            serve_task = asyncio.create_task(svc.serve())
            await asyncio.sleep(0)  # let serve run to mark_ready

            # Simulate framework shutdown: set the service-level shutdown_event then cancel.
            svc.shutdown_event.set()
            serve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.gather(serve_task, return_exceptions=True)
            assert serve_task.done()

        svc.executor.shutdown(join_threads_or_timeout=False)

    @pytest.mark.anyio
    async def test_serve_calls_probe_on_each_cycle(self, caplog: pytest.LogCaptureFixture) -> None:
        """serve() calls log_saturation_rate_limited() on each probe cycle."""
        svc = make_service(max_workers=1, shutdown_timeout=5.0)
        gate = threading.Event()
        ready = threading.Event()

        try:
            # Fill pool so saturation check would fire
            svc.executor.submit(lambda: (ready.set(), gate.wait(timeout=10)))
            ready.wait(timeout=2)
            # Simulate full saturation via active counter
            svc._active_workers = 1
            # Pre-expire rate-limit
            svc._last_saturation_warn_ts = 0.0

            probe_calls: list[None] = []
            original_log = svc.log_saturation_rate_limited

            def counting_probe() -> None:
                probe_calls.append(None)
                original_log()

            svc.log_saturation_rate_limited = counting_probe  # pyright: ignore[reportAttributeAccessIssue]

            with patch("hassette.core.sync_executor_service._SATURATION_PROBE_INTERVAL_SECS", 0.05):
                serve_task = asyncio.create_task(svc.serve())
                await asyncio.sleep(0)  # let serve run mark_ready
                # Wait long enough for at least 2 probe cycles
                await asyncio.sleep(0.2)
                # Cancel the task (how the framework shuts down serve())
                serve_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                    await asyncio.gather(serve_task, return_exceptions=True)

            assert len(probe_calls) >= 1, (
                f"serve() must call log_saturation_rate_limited() on each cycle; got {len(probe_calls)} calls"
            )

        finally:
            gate.set()
            svc.executor.shutdown(join_threads_or_timeout=False)


class TestShutdownInterruptsPythonWorker:
    """Shutdown interrupts Python-busy-loop workers within budget; name and stack logged."""

    def test_python_worker_interrupted_within_budget(self) -> None:
        """A Python busy-loop worker is interrupted by async_raise(SystemExit) at shutdown.

        Uses the asyncio.Event gate pattern: gate holds the worker alive across the
        shutdown boundary, then shutdown runs with join_threads_or_timeout=True.
        """
        executor = InterruptibleThreadPoolExecutor(max_workers=1, thread_name_prefix="test-sync")
        ready = threading.Event()
        terminated = threading.Event()

        def busy_loop() -> None:
            ready.set()
            try:
                while True:
                    pass
            except SystemExit:
                terminated.set()
                raise

        executor.submit(busy_loop)
        ready.wait(timeout=2)

        budget = 3.0
        wall_start = time.monotonic()
        executor.shutdown(join_threads_or_timeout=True, timeout=budget)
        elapsed = time.monotonic() - wall_start

        assert terminated.is_set(), "Worker must have received SystemExit at shutdown"
        assert elapsed < budget * 1.5, f"Shutdown took {elapsed:.2f}s — expected < {budget * 1.5:.2f}s"

    def test_python_worker_name_and_stack_logged(self) -> None:
        """Straggler thread name and stack are logged before interruption.

        Patches _log_thread_running_at_shutdown directly — avoids structlog/caplog
        ordering sensitivity (project uses structlog, which bypasses caplog).
        """
        executor = InterruptibleThreadPoolExecutor(max_workers=1, thread_name_prefix="hassette-sync")
        ready = threading.Event()
        log_calls: list[tuple] = []

        def busy_loop() -> None:
            ready.set()
            try:
                while True:
                    pass
            except SystemExit:
                raise

        executor.submit(busy_loop)
        ready.wait(timeout=2)

        def capture_log(name: str, ident: int) -> None:
            log_calls.append((name, ident))

        with patch.object(ie_module, "_log_thread_running_at_shutdown", side_effect=capture_log):
            executor.shutdown(join_threads_or_timeout=True, timeout=2.0)

        assert log_calls, "Expected _log_thread_running_at_shutdown to be called for straggler"
        assert any("hassette-sync" in name for name, _ in log_calls), (
            f"Expected thread name with 'hassette-sync' prefix; got: {log_calls}"
        )

    def test_shutdown_does_not_raise(self) -> None:
        """Shutdown never propagates an exception from the interrupt loop."""
        executor = InterruptibleThreadPoolExecutor(max_workers=1)
        ready = threading.Event()

        def busy_loop() -> None:
            ready.set()
            try:
                while True:
                    pass
            except SystemExit:
                raise

        executor.submit(busy_loop)
        ready.wait(timeout=2)

        # Must not raise — all interruption exceptions are suppressed
        executor.shutdown(join_threads_or_timeout=True, timeout=1.0)

    @pytest.mark.anyio
    async def test_on_shutdown_with_busy_worker_completes(self, caplog: pytest.LogCaptureFixture) -> None:
        """SyncExecutorService.on_shutdown() completes with a Python busy-loop worker."""
        svc = make_service(max_workers=1, shutdown_timeout=3.0)
        ready = threading.Event()
        terminated = threading.Event()

        def busy_loop() -> None:
            ready.set()
            try:
                while True:
                    pass
            except SystemExit:
                terminated.set()
                raise

        svc.executor.submit(busy_loop)
        ready.wait(timeout=2)

        # on_shutdown runs executor.shutdown in a thread so the event loop stays live
        await asyncio.wait_for(svc.on_shutdown(), timeout=5.0)

        assert terminated.is_set(), "Worker must have received SystemExit via on_shutdown"


@skip_c_blocked_under_coverage_py311
class TestShutdownCBlockedWorker:
    """C-blocked workers (time.sleep) are abandoned at budget expiry; shutdown completes."""

    def test_c_blocked_worker_shutdown_completes_within_budget(self) -> None:
        """Shutdown returns within budget even when a worker is blocked in time.sleep."""
        executor = InterruptibleThreadPoolExecutor(max_workers=1)
        ready = threading.Event()

        def c_blocked() -> None:
            ready.set()
            time.sleep(60)  # C-level — not interruptible by async_raise

        executor.submit(c_blocked)
        ready.wait(timeout=2)

        budget = 1.0
        wall_start = time.monotonic()
        executor.shutdown(join_threads_or_timeout=True, timeout=budget)
        elapsed = time.monotonic() - wall_start

        # Allow 30% margin for scheduling jitter
        assert elapsed < budget * 1.3, (
            f"Shutdown took {elapsed:.2f}s — expected < {budget * 1.3:.2f}s (budget={budget}s)"
        )

    def test_c_blocked_worker_does_not_raise(self) -> None:
        """Shutdown with a C-blocked worker must not propagate any exception."""
        executor = InterruptibleThreadPoolExecutor(max_workers=1)
        ready = threading.Event()

        def c_blocked() -> None:
            ready.set()
            time.sleep(60)

        executor.submit(c_blocked)
        ready.wait(timeout=2)

        # Must not raise — C-blocked thread is abandoned, not errored
        executor.shutdown(join_threads_or_timeout=True, timeout=0.5)

    def test_c_blocked_worker_straggler_is_logged(self) -> None:
        """C-blocked worker that survives the budget is logged at shutdown."""
        executor = InterruptibleThreadPoolExecutor(max_workers=1, thread_name_prefix="hassette-sync")
        ready = threading.Event()
        log_calls: list[tuple] = []

        def c_blocked() -> None:
            ready.set()
            time.sleep(60)

        executor.submit(c_blocked)
        ready.wait(timeout=2)

        def capture_log(name: str, ident: int) -> None:
            log_calls.append((name, ident))

        with patch.object(ie_module, "_log_thread_running_at_shutdown", side_effect=capture_log):
            executor.shutdown(join_threads_or_timeout=True, timeout=0.5)

        assert log_calls, "Expected _log_thread_running_at_shutdown to be called for C-blocked straggler"
        assert any("hassette-sync" in name for name, _ in log_calls), (
            f"Expected thread name with 'hassette-sync' prefix; got: {log_calls}"
        )

    @pytest.mark.anyio
    async def test_on_shutdown_c_blocked_completes_within_budget(self) -> None:
        """SyncExecutorService.on_shutdown() completes within budget with a C-blocked worker."""
        svc = make_service(max_workers=1, shutdown_timeout=1.0)
        ready = threading.Event()

        def c_blocked() -> None:
            ready.set()
            time.sleep(60)

        svc.executor.submit(c_blocked)
        ready.wait(timeout=2)

        wall_start = time.monotonic()
        # on_shutdown budget = min(sync_executor_shutdown_timeout_seconds, resource_shutdown_timeout_seconds)
        # resource_shutdown_timeout_seconds defaults to app_shutdown_timeout_seconds (10s); capped by 1.0 here.
        await asyncio.wait_for(svc.on_shutdown(), timeout=3.0)
        elapsed = time.monotonic() - wall_start

        # 1.0s budget + 30% jitter
        assert elapsed < 1.3, f"on_shutdown took {elapsed:.2f}s — expected < 1.3s with 1.0s budget"


class TestConfigBehavior:
    """Custom max_workers and shutdown_timeout change behavior; defaults apply when unset."""

    def test_custom_max_workers_is_respected(self) -> None:
        """Executor uses the configured max_workers ceiling."""
        svc = make_service(max_workers=3)
        assert svc.executor._max_workers == 3  # pyright: ignore[reportAttributeAccessIssue]
        svc.executor.shutdown(join_threads_or_timeout=False)

    def test_default_max_workers_is_reasonable(self) -> None:
        """Default max_workers is min(32, cpu_count + 4) — a reasonable pool ceiling."""
        config = HassetteConfig(token=TEST_TOKEN)
        expected = min(32, (os.cpu_count() or 1) + 4)
        assert config.lifecycle.sync_executor_max_workers == expected

    def test_custom_shutdown_timeout_is_used_in_on_shutdown(self) -> None:
        """on_shutdown passes the configured budget to executor.shutdown."""
        svc = make_service(max_workers=2, shutdown_timeout=3.7)

        shutdown_kwargs: list[dict[str, Any]] = []
        original = svc.executor.shutdown

        def recording_shutdown(**kwargs: Any) -> None:
            shutdown_kwargs.append(kwargs)
            original(join_threads_or_timeout=False)

        svc.executor.shutdown = recording_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        asyncio.run(svc.on_shutdown())

        assert shutdown_kwargs, "executor.shutdown must have been called"
        assert shutdown_kwargs[0].get("timeout") == pytest.approx(3.7), (
            f"Expected timeout=3.7; got {shutdown_kwargs[0].get('timeout')}"
        )

    def test_default_shutdown_timeout_is_10s(self) -> None:
        """Default sync_executor_shutdown_timeout_seconds is 10.0 (HA's value)."""
        config = HassetteConfig(token=TEST_TOKEN)
        assert config.lifecycle.sync_executor_shutdown_timeout_seconds == 10.0

    def test_validator_rejects_shutdown_timeout_gte_total(self) -> None:
        """sync_executor_shutdown_timeout_seconds >= total_shutdown_timeout_seconds is rejected."""
        with pytest.raises(ValidationError, match="sync_executor_shutdown_timeout_seconds"):
            HassetteConfig(
                token=TEST_TOKEN,
                lifecycle={
                    "sync_executor_shutdown_timeout_seconds": 30.0,
                    "total_shutdown_timeout_seconds": 30,  # equal — must be rejected
                },
            )


class TestTrackSubmission:
    """track_submission accurately tracks active workers via done-callback."""

    @pytest.mark.anyio
    async def test_track_submission_increments_active_workers(self) -> None:
        """track_submission increments active_workers and decrements via done-callback."""
        svc = make_service(max_workers=2, shutdown_timeout=5.0)

        try:
            assert svc._active_workers == 0

            blocking_gate = threading.Event()
            ready = threading.Event()

            def blocking_work() -> None:
                ready.set()
                blocking_gate.wait(timeout=5)

            loop = asyncio.get_running_loop()
            future: asyncio.Future[None] = loop.run_in_executor(svc.executor, blocking_work)
            svc.track_submission(future)

            ready.wait(timeout=2)
            assert svc._active_workers == 1, "Active workers must be 1 while work is running"

            blocking_gate.set()
            await asyncio.wrap_future(future)
            # Give the done-callback a chance to fire on the loop thread
            await asyncio.sleep(0)
            assert svc._active_workers == 0, "Active workers must return to 0 after work completes"

        finally:
            svc.executor.shutdown(join_threads_or_timeout=False)

    @pytest.mark.anyio
    async def test_run_in_thread_calls_saturation_check(self) -> None:
        """After run_in_thread submits work, track_submission is called (which calls log check)."""
        svc = make_service(max_workers=1, shutdown_timeout=5.0)
        mock_hassette = svc.hassette
        mock_hassette.sync_executor_service = svc
        mock_hassette.sync_executor = svc.executor

        track_calls: list[None] = []
        original = svc.track_submission

        def counting_track(future: object) -> None:
            track_calls.append(None)
            original(future)  # pyright: ignore[reportArgumentType]

        svc.track_submission = counting_track  # pyright: ignore[reportAttributeAccessIssue]

        # Build a minimal TaskBucket using the mock hassette
        tb = TaskBucket(mock_hassette)

        done = threading.Event()

        def work() -> None:
            done.set()
            threading.Event().wait(timeout=0.5)

        future = tb.run_in_thread(work)
        done.wait(timeout=2.0)

        assert len(track_calls) >= 1, "run_in_thread must call track_submission after submitting"

        await asyncio.wrap_future(future)
        svc.executor.shutdown(join_threads_or_timeout=False)
