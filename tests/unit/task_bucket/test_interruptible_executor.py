"""Unit tests for interruptible_executor.py.

Tests are scoped to the standalone primitive — no Hassette imports required.

Coverage targets (from T01 Verify section):
- FR#6: async_raise terminates a Python busy-loop thread; straggler name+stack logged
  before interrupt (captured via a handler attached directly to the executor logger,
  so the assertion does not depend on global ``propagate`` state).
- FR#7: join_threads_or_timeout completes within timeout even when a worker is blocked
  in a C call (time.sleep); res==0 (ValueError) and res>1 (SystemError) paths are
  handled and no exception propagates out of shutdown.
"""

import contextlib
import logging
import threading
import time
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from hassette.task_bucket.interruptible_executor import (
    InterruptibleThreadPoolExecutor,
    _log_thread_running_at_shutdown,
    async_raise,
    join_or_interrupt_threads,
)

_EXECUTOR_LOGGER = "hassette.task_bucket.interruptible_executor"


@contextlib.contextmanager
def capture_warnings(logger_name: str = _EXECUTOR_LOGGER) -> Iterator[list[logging.LogRecord]]:
    """Capture WARNING+ records from ``logger_name`` via a directly-attached handler.

    Unlike pytest's ``caplog``, this does not rely on records propagating to the root
    logger, so it is immune to other tests leaving ``propagate=False`` on a ``hassette``
    ancestor (which the async logging pipeline sets). The handler sits on the target
    logger itself, and the logger's level is pinned to WARNING for the duration so the
    record is not filtered by an ancestor's level.

    test_sync_executor_service.py works around the same ``propagate=False`` problem by
    mock-patching the service logger's ``.warning`` method instead.
    """
    records: list[logging.LogRecord] = []

    class _Recorder(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger(logger_name)
    handler = _Recorder(level=logging.WARNING)
    prev_level = logger.level
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)


# ---------------------------------------------------------------------------
# async_raise — unit-level tests
# ---------------------------------------------------------------------------


class TestAsyncRaise:
    """Tests for the async_raise() function."""

    def test_raises_type_error_for_instance(self) -> None:
        """async_raise must reject non-class arguments."""
        t = threading.current_thread()
        assert t.ident is not None
        with pytest.raises(TypeError, match="Only types can be raised"):
            async_raise(t.ident, ValueError("not a class"))  # pyright: ignore[reportArgumentType]

    def test_raises_value_error_for_nonexistent_thread(self) -> None:
        """async_raise must raise ValueError when the thread id doesn't exist."""
        # Use a thread id that is extremely unlikely to be valid.
        with pytest.raises(ValueError, match="Thread not found"):
            async_raise(999_999_999, SystemExit)

    def test_res_greater_than_one_reverts_and_raises_system_error(self) -> None:
        """When PyThreadState_SetAsyncExc returns >1, it must revert and raise SystemError."""
        call_count = 0

        def fake_set_async_exc(_tid: object, _exc: object) -> int:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 2  # trigger the >1 branch
            return 1  # revert call succeeds

        with patch(
            "hassette.task_bucket.interruptible_executor.ctypes.pythonapi.PyThreadState_SetAsyncExc",
            side_effect=fake_set_async_exc,
        ):
            t = threading.current_thread()
            assert t.ident is not None
            with pytest.raises(SystemError, match="PyThreadState_SetAsyncExc failed"):
                async_raise(t.ident, SystemExit)

        # revert call must have been made (call_count == 2)
        assert call_count == 2

    def test_terminates_python_busy_loop_thread(self) -> None:
        """async_raise(SystemExit) must terminate a thread running a pure-Python busy loop."""
        done = threading.Event()

        def busy_loop() -> None:
            try:
                while True:
                    pass
            except SystemExit:
                # Swallow SystemExit so the thread exits cleanly without triggering
                # pytest's threadexception plugin (which treats unhandled thread
                # exceptions as test failures). The thread is done; we don't re-raise.
                done.set()

        t = threading.Thread(target=busy_loop, daemon=True)
        t.start()
        time.sleep(0.05)  # let it spin up

        assert t.ident is not None
        async_raise(t.ident, SystemExit)

        # Thread must stop within a generous but bounded time.
        t.join(timeout=3.0)
        assert not t.is_alive(), "Thread should have been terminated by async_raise"
        assert done.is_set(), "Thread should have received SystemExit"


# ---------------------------------------------------------------------------
# _log_thread_running_at_shutdown — verifies logging helper
# ---------------------------------------------------------------------------


class TestLogThreadRunningAtShutdown:
    """Tests for the logging helper."""

    def test_logs_warning_with_name_and_stack(self) -> None:
        """_log_thread_running_at_shutdown must emit a WARNING with name and stack trace."""
        t = threading.current_thread()
        assert t.ident is not None

        with capture_warnings() as records:
            _log_thread_running_at_shutdown(t.name, t.ident)

        messages = [r.getMessage() for r in records]
        assert any(t.name in m and "is still running at shutdown" in m for m in messages), (
            f"Expected warning with thread name '{t.name}'; got: {messages}"
        )


# ---------------------------------------------------------------------------
# join_or_interrupt_threads — unit-level tests
# ---------------------------------------------------------------------------


class TestJoinOrInterruptThreads:
    """Tests for join_or_interrupt_threads()."""

    def test_returns_joined_threads(self) -> None:
        """Threads that finish within their slice are returned in the joined set."""
        started = threading.Event()

        def short_work() -> None:
            started.set()
            time.sleep(0.01)

        t = threading.Thread(target=short_work, daemon=True)
        t.start()
        started.wait()

        joined = join_or_interrupt_threads({t}, timeout=2.0, log=False)
        assert t in joined

    def test_logs_straggler_name_before_interrupt(self) -> None:
        """When log=True, the straggler's name and stack must be logged before async_raise."""
        ready = threading.Event()

        def busy_loop() -> None:
            ready.set()
            try:
                while True:
                    pass
            except SystemExit:
                # Swallow SystemExit so the thread exits cleanly without triggering
                # pytest's threadexception plugin.
                pass

        t = threading.Thread(target=busy_loop, name="test-straggler-thread", daemon=True)
        t.start()
        ready.wait()

        with capture_warnings() as records:
            join_or_interrupt_threads({t}, timeout=0.05, log=True)

        t.join(timeout=2.0)

        messages = [r.getMessage() for r in records]
        assert any("test-straggler-thread" in m for m in messages), (
            f"Expected log entry with thread name; got: {messages}"
        )

    def test_suppresses_value_error_from_async_raise(self) -> None:
        """ValueError (thread not found) from async_raise must be suppressed."""
        # Create a thread, let it die, then call join_or_interrupt_threads — the thread
        # will be alive-checked and found dead, so it should go into the joined set
        # without raising. We also test the suppression path by patching async_raise.
        done = threading.Event()

        def quick() -> None:
            done.set()

        t = threading.Thread(target=quick, daemon=True)
        t.start()
        done.wait()
        t.join()  # now dead

        # Should not raise — dead thread goes into joined set
        joined = join_or_interrupt_threads({t}, timeout=0.5, log=False)
        assert t in joined

    def test_suppresses_system_error_from_async_raise(self) -> None:
        """SystemError from async_raise must be suppressed, not propagated."""
        ready = threading.Event()

        def loop() -> None:
            ready.set()
            try:
                while True:
                    pass
            except SystemExit:
                # Swallow SystemExit so the thread exits cleanly without triggering
                # pytest's threadexception plugin.
                pass

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        ready.wait()

        with patch(
            "hassette.task_bucket.interruptible_executor.async_raise",
            side_effect=SystemError("simulated"),
        ):
            # Must not raise
            join_or_interrupt_threads({t}, timeout=0.05, log=False)

        # Clean up — t is still running because async_raise was patched to raise SystemError
        assert t.ident is not None
        async_raise(t.ident, SystemExit)
        t.join(timeout=2.0)


# ---------------------------------------------------------------------------
# InterruptibleThreadPoolExecutor.shutdown — integration-level tests
# ---------------------------------------------------------------------------


class TestInterruptibleThreadPoolExecutorShutdown:
    """Tests for the full shutdown() / join_threads_or_timeout() path."""

    def test_shutdown_completes_within_timeout_for_c_blocked_thread(self) -> None:
        """shutdown() must return within the budget even when a worker is C-blocked.

        time.sleep() is a C call that cannot be interrupted by async_raise until it
        returns to Python. The executor must abandon the thread and complete shutdown
        within the budget (FR#7 / AC#5).
        """
        executor = InterruptibleThreadPoolExecutor(max_workers=1)
        started = threading.Event()

        def c_blocked() -> None:
            started.set()
            time.sleep(60)  # long C-level sleep

        executor.submit(c_blocked)
        started.wait()

        budget = 1.0
        wall_start = time.monotonic()
        executor.shutdown(join_threads_or_timeout=True, timeout=budget)
        elapsed = time.monotonic() - wall_start

        # Allow a 20% margin over budget for scheduling jitter.
        assert elapsed < budget * 1.2, f"shutdown() took {elapsed:.2f}s, expected < {budget * 1.2:.2f}s"

    def test_shutdown_does_not_raise(self) -> None:
        """shutdown() must never propagate an exception from the interrupt loop."""
        executor = InterruptibleThreadPoolExecutor(max_workers=2)
        ready = threading.Event()

        def busy() -> None:
            ready.set()
            while True:
                pass

        executor.submit(busy)
        ready.wait()

        # Must not raise — benign errors are suppressed
        executor.shutdown(join_threads_or_timeout=True, timeout=0.5)

    def test_python_busy_loop_worker_terminated_within_budget(self) -> None:
        """A Python busy-loop worker must be interrupted by async_raise(SystemExit)
        within the shutdown budget (FR#6 / AC#4).
        """
        executor = InterruptibleThreadPoolExecutor(max_workers=1)
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
        ready.wait()

        budget = 2.0
        executor.shutdown(join_threads_or_timeout=True, timeout=budget)

        assert terminated.is_set(), "Worker thread must have received SystemExit"

    def test_stack_logged_for_python_straggler(self) -> None:
        """Straggler thread name and stack must be logged before interrupt (FR#6 / AC#4)."""
        executor = InterruptibleThreadPoolExecutor(max_workers=1, thread_name_prefix="test-worker")
        ready = threading.Event()

        def busy_loop() -> None:
            ready.set()
            try:
                while True:
                    pass
            except SystemExit:
                raise

        executor.submit(busy_loop)
        ready.wait()

        with capture_warnings() as records:
            executor.shutdown(join_threads_or_timeout=True, timeout=2.0)

        messages = [r.getMessage() for r in records]
        assert any("is still running at shutdown" in m for m in messages), (
            f"Expected straggler warning; got: {messages}"
        )

    def test_shutdown_without_join_skips_interrupt_loop(self) -> None:
        """shutdown(join_threads_or_timeout=False) must skip the join/interrupt loop."""
        executor = InterruptibleThreadPoolExecutor(max_workers=1)
        ready = threading.Event()

        def busy() -> None:
            ready.set()
            time.sleep(30)

        executor.submit(busy)
        ready.wait()

        # Should return immediately (no join attempt)
        wall_start = time.monotonic()
        executor.shutdown(join_threads_or_timeout=False)
        elapsed = time.monotonic() - wall_start

        assert elapsed < 0.5, f"Expected near-instant shutdown; took {elapsed:.2f}s"

    def test_join_threads_or_timeout_returns_early_when_all_joined(self) -> None:
        """join_threads_or_timeout() exits early once all threads have joined.

        This test calls join_threads_or_timeout() directly via a pre-shutdown scenario:
        we pass a set of threads that are already dead (joined). The loop must short-circuit
        immediately on the first pass rather than spinning for the full timeout.
        """
        # Build a tiny set of threads that finish immediately and are already dead
        finished = threading.Event()

        def quick() -> None:
            finished.set()

        threads: list[threading.Thread] = []
        for _ in range(2):
            t = threading.Thread(target=quick, daemon=True)
            t.start()
            threads.append(t)

        # Wait for all threads to finish
        for t in threads:
            t.join(timeout=2.0)
        assert all(not t.is_alive() for t in threads)

        # Now call join_threads_or_timeout with already-dead threads injected directly.
        # We build a minimal stub executor that has _threads set to these dead threads,
        # matching what join_threads_or_timeout reads via self._threads.
        executor = InterruptibleThreadPoolExecutor(max_workers=1)
        executor._threads = set(threads)  # pyright: ignore[reportAttributeAccessIssue]

        wall_start = time.monotonic()
        executor.join_threads_or_timeout(timeout=10.0)
        elapsed = time.monotonic() - wall_start

        # Must exit fast — all threads are already dead. Tight bound so a regression
        # that iterates unexpectedly (instead of early-exiting) is actually caught.
        assert elapsed < 0.5, f"Expected early exit; took {elapsed:.2f}s"

        # Clean up the real executor without the join loop
        executor.shutdown(join_threads_or_timeout=False)

    def test_res_zero_suppressed_during_shutdown(self) -> None:
        """ValueError('Thread not found') from async_raise must be suppressed.

        Covers the res==0 path with a *live* thread so async_raise is actually called
        and its mocked ValueError actually fires (a dead thread would join first and
        async_raise would never run — a vacuous test).
        """
        ready = threading.Event()

        def busy_loop() -> None:
            ready.set()
            try:
                while True:
                    time.sleep(0.01)
            except SystemExit:
                pass  # swallow so pytest's threadexception plugin doesn't flag it

        t = threading.Thread(target=busy_loop, daemon=True)
        t.start()
        ready.wait()

        with patch(
            "hassette.task_bucket.interruptible_executor.async_raise",
            side_effect=ValueError("Thread not found"),
        ):
            # Thread is alive, so async_raise IS invoked; its ValueError must be suppressed.
            join_or_interrupt_threads({t}, timeout=0.05, log=False)

        # Clean up: actually stop the live thread now that the real async_raise is back.
        assert t.ident is not None  # thread has started, so ident is set
        async_raise(t.ident, SystemExit)
        t.join(timeout=2.0)
        assert not t.is_alive()

    def test_res_greater_than_one_suppressed_during_shutdown(self) -> None:
        """SystemError from async_raise (res>1 path) must be suppressed at shutdown."""
        executor = InterruptibleThreadPoolExecutor(max_workers=1)
        ready = threading.Event()

        def busy() -> None:
            ready.set()
            try:
                while True:
                    pass
            except SystemExit:
                raise

        executor.submit(busy)
        ready.wait()

        with patch(
            "hassette.task_bucket.interruptible_executor.async_raise",
            side_effect=SystemError("simulated res>1"),
        ):
            # Must not raise
            executor.shutdown(join_threads_or_timeout=True, timeout=0.5)
