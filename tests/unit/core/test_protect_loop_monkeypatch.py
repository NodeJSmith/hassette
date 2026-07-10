"""Unit tests for the Tier 2 protect-loop monkeypatch.

Covers:
    - each patched primitive responds per behavior before the call proceeds
    - off-loop calls pass through unflagged
    - enablement matrix: dev→ON, prod default→OFF, prod+flag→ON
    - idempotent install; uninstall restores originals; re-install is clean
    - dev_mode + filterwarnings("error") causes loop-thread time.sleep to RAISE
      BEFORE sleeping (the sleep never happens); prod without flag → no patch
    - MonkeypatchEvent dataclass fields are populated correctly
"""

import asyncio
import builtins
import contextlib
import glob as glob_module
import os
import socket
import threading
import time
import warnings
from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import hassette.core.block_io_guard as guard_mod
from hassette.core.block_io_guard import (
    MonkeypatchEvent,
    install,
    is_installed,
    uninstall,
)
from hassette.core.command_executor import ExecutionMarker
from hassette.exceptions import HassetteBlockingIOWarning
from hassette.types.enums import BlockingIOBehavior

_REAL_SLEEP = time.__dict__["sleep"]  # stash before any test mutates time.sleep
_REAL_OPEN = builtins.__dict__["open"]


def make_hassette(
    *,
    dev_mode: bool = True,
    deep_detection_enabled: bool | None = None,
    allow_deep_detection_in_prod: bool = False,
    behavior: BlockingIOBehavior | None = None,
) -> MagicMock:
    """Minimal mock Hassette for guard tests."""
    cfg = MagicMock()
    cfg.dev_mode = dev_mode
    cfg.blocking_io.deep_detection_enabled = deep_detection_enabled
    cfg.blocking_io.allow_deep_detection_in_prod = allow_deep_detection_in_prod
    cfg.blocking_io.behavior = behavior
    h = MagicMock()
    h.config = cfg
    # Resolve owner as hassette itself when no app is live.
    h.app_config.blocking_io_behavior = None
    h.hassette.config.blocking_io.behavior = behavior
    h.app_handler.get.return_value = None
    return h


def make_executor(*, app_key: str | None = "test_app", instance_index: int | None = 0) -> MagicMock:
    executor = MagicMock()
    executor.current_execution = ExecutionMarker(
        app_key=app_key,
        instance_name=None,
        execution_id="exec-t04",
        started_at=time.monotonic(),
        instance_index=instance_index,
    )
    return executor


@pytest.fixture(autouse=True)
def ensure_uninstall() -> Iterator[None]:
    """Guarantee Tier 2 patches are never leaked between tests.

    Runs try/finally so even a test that raises mid-body cannot leave patches
    active for subsequent tests (the top risk the spec calls out).
    """
    # Each test starts clean.
    uninstall()
    yield
    # Always restore, even if the test raised.
    uninstall()
    # Verify the known primitives are not patched.
    assert time.sleep is _REAL_SLEEP, "time.sleep leaked between tests"
    assert builtins.open is _REAL_OPEN, "builtins.open leaked between tests"


class TestEnablementMatrix:
    def test_dev_mode_installs(self) -> None:
        """dev_mode=True → Tier 2 installs."""
        h = make_hassette(dev_mode=True)
        ex = make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is True
        assert is_installed()
        assert time.sleep is not _REAL_SLEEP

    def test_prod_default_does_not_install(self) -> None:
        """Production without flag → NOT patched."""
        h = make_hassette(dev_mode=False, allow_deep_detection_in_prod=False)
        ex = make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is False
        assert not is_installed()
        assert time.sleep is _REAL_SLEEP

    def test_prod_with_flag_and_explicit_enabled_installs(self) -> None:
        """Production with deep_detection_enabled=True + allow_deep_detection_in_prod=True → patched.

        The enablement spec: deep_detection_enabled=None → follows dev_mode. With dev_mode=False
        that yields enabled=False → returns False early. To reach the prod flag check, the operator
        must set deep_detection_enabled=True explicitly; the prod gate then gates on
        allow_deep_detection_in_prod.
        """
        h = make_hassette(dev_mode=False, deep_detection_enabled=True, allow_deep_detection_in_prod=True)
        ex = make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is True
        assert is_installed()
        assert time.sleep is not _REAL_SLEEP

    def test_explicit_disabled_overrides_dev_mode(self) -> None:
        """deep_detection_enabled=False overrides dev_mode=True."""
        h = make_hassette(dev_mode=True, deep_detection_enabled=False)
        ex = make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is False
        assert not is_installed()
        assert time.sleep is _REAL_SLEEP

    def test_explicit_enabled_prod_no_allow_flag_not_installed(self) -> None:
        """deep_detection_enabled=True in prod without allow flag → NOT installed (prod gate applies).

        Flow:
            enabled = True (not None)
            if not enabled: return False   # skip
            if dev_mode: return True       # False → continue
            return allow_deep_detection_in_prod  # False → NOT installed
        """
        h = make_hassette(dev_mode=False, deep_detection_enabled=True, allow_deep_detection_in_prod=False)
        ex = make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is False
        assert not is_installed()

    def test_explicit_enabled_prod_with_allow_flag(self) -> None:
        """deep_detection_enabled=True + prod + allow flag → installed."""
        h = make_hassette(dev_mode=False, deep_detection_enabled=True, allow_deep_detection_in_prod=True)
        ex = make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is True
        assert is_installed()


class TestIdempotencyAndLeak:
    def test_double_install_is_noop(self) -> None:
        """Second install without uninstall is a no-op (returns False)."""
        h = make_hassette()
        ex = make_executor()
        tid = threading.get_ident()
        first = install(h, loop_thread_id=tid, executor=ex)
        second = install(h, loop_thread_id=tid, executor=ex)
        assert first is True
        assert second is False  # no-op

    def test_uninstall_when_not_installed_is_noop(self) -> None:
        """uninstall() when not installed returns False and does not raise."""
        result = uninstall()
        assert result is False

    def test_uninstall_restores_time_sleep(self) -> None:
        """After uninstall, time.sleep is the original."""
        h = make_hassette()
        ex = make_executor()
        install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert time.sleep is not _REAL_SLEEP
        uninstall()
        assert time.sleep is _REAL_SLEEP

    def test_uninstall_restores_builtins_open(self) -> None:
        """After uninstall, builtins.open is the original."""
        h = make_hassette()
        ex = make_executor()
        install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert builtins.open is not _REAL_OPEN
        uninstall()
        assert builtins.open is _REAL_OPEN

    def test_uninstall_restores_all_primitives(self) -> None:
        """After uninstall, every primitive in the table is its original."""
        originals: dict[str, object] = {
            "time.sleep": _REAL_SLEEP,
            "builtins.open": _REAL_OPEN,
            "os.listdir": os.listdir,
            "os.scandir": os.scandir,
            "os.walk": os.walk,
            "glob.glob": glob_module.glob,
            "socket.connect": socket.socket.connect,
            "socket.recv": socket.socket.recv,
            "socket.send": socket.socket.send,
        }
        h = make_hassette()
        ex = make_executor()
        install(h, loop_thread_id=threading.get_ident(), executor=ex)
        uninstall()
        assert time.sleep is originals["time.sleep"]
        assert builtins.open is originals["builtins.open"]
        assert os.listdir is originals["os.listdir"]
        assert os.scandir is originals["os.scandir"]
        assert os.walk is originals["os.walk"]
        assert glob_module.glob is originals["glob.glob"]
        assert socket.socket.connect is originals["socket.connect"]
        assert socket.socket.recv is originals["socket.recv"]
        assert socket.socket.send is originals["socket.send"]

    def test_reinstall_after_uninstall_works(self) -> None:
        """After uninstall, a re-install succeeds and patches primitives again."""
        h = make_hassette()
        ex = make_executor()
        tid = threading.get_ident()
        install(h, loop_thread_id=tid, executor=ex)
        uninstall()
        assert time.sleep is _REAL_SLEEP
        second = install(h, loop_thread_id=tid, executor=ex)
        assert second is True
        assert time.sleep is not _REAL_SLEEP

    def test_uninstall_by_non_owner_is_noop(self) -> None:
        """A non-owning instance cannot uninstall the owner's process-global patches.

        Tier 2 has a single owner. If a second Hassette instance's shutdown called uninstall,
        it would disable call-site interception for the still-running owner. Passing the caller
        to uninstall() makes it no-op when the caller is not the owner.
        """
        owner = make_hassette()
        other = make_hassette()
        ex = make_executor()
        install(owner, loop_thread_id=threading.get_ident(), executor=ex)

        # Non-owner uninstall is refused — patches stay live for the owner.
        assert uninstall(other) is False
        assert is_installed()
        assert time.sleep is not _REAL_SLEEP

        # The owner can still uninstall its own patches.
        assert uninstall(owner) is True
        assert not is_installed()
        assert time.sleep is _REAL_SLEEP

    def test_is_installed_reflects_state(self) -> None:
        """is_installed() tracks install/uninstall state correctly."""
        assert not is_installed()
        h = make_hassette()
        ex = make_executor()
        install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert is_installed()
        uninstall()
        assert not is_installed()


class TestOffLoopGate:
    def test_time_sleep_off_loop_thread_passes_through(self) -> None:
        """time.sleep called from a worker thread is not flagged."""
        fake_loop_thread_id = threading.get_ident() + 9999  # different from current thread
        h = make_hassette()
        ex = make_executor()
        install(h, loop_thread_id=fake_loop_thread_id, executor=ex)

        warning_fired = False

        def worker() -> None:
            nonlocal warning_fired
            with warnings.catch_warnings():
                warnings.filterwarnings("error", category=HassetteBlockingIOWarning)
                try:
                    # Runs on a thread that is NOT the simulated loop thread.
                    # Should pass through without triggering the warning.
                    time.sleep(0)
                except HassetteBlockingIOWarning:
                    warning_fired = True

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)
        assert not warning_fired, "Worker-thread call triggered a blocking-IO warning"

    def test_loop_thread_call_fires_warning(self) -> None:
        """time.sleep on the loop thread (our thread) triggers warning."""
        tid = threading.get_ident()
        h = make_hassette()
        ex = make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        assert any(issubclass(w.category, HassetteBlockingIOWarning) for w in caught), (
            "Expected HassetteBlockingIOWarning on loop-thread time.sleep"
        )


class TestPrimitiveWarnBehavior:
    def test_time_sleep_loop_thread_warns(self) -> None:
        """time.sleep on loop thread emits HassetteBlockingIOWarning (WARN behavior)."""
        tid = threading.get_ident()
        h = make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        msgs = [str(w.message) for w in caught if issubclass(w.category, HassetteBlockingIOWarning)]
        assert msgs, "Expected a HassetteBlockingIOWarning for time.sleep on loop thread"
        assert "time.sleep" in msgs[0]
        assert "test_app" in msgs[0]

    def test_open_loop_thread_warns(self, tmp_path: Path) -> None:
        """builtins.open on loop thread emits HassetteBlockingIOWarning (WARN behavior)."""
        tid = threading.get_ident()
        h = make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        target = tmp_path / "test.txt"
        target.write_text("hello")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            with open(target) as fh:  # intentional: testing the patched builtins.open
                fh.read()

        msgs = [str(w.message) for w in caught if issubclass(w.category, HassetteBlockingIOWarning)]
        assert msgs, "Expected a HassetteBlockingIOWarning for open() on loop thread"
        assert "builtins.open" in msgs[0]

    def test_ignore_behavior_suppresses_warning(self) -> None:
        """IGNORE behavior → no warning, original is still called."""
        tid = threading.get_ident()
        h = make_hassette(behavior=BlockingIOBehavior.IGNORE)
        ex = make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        # Wire h.hassette.config.blocking_io.behavior so resolver reads IGNORE.
        h.hassette.config.blocking_io.behavior = BlockingIOBehavior.IGNORE

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        assert not any(issubclass(w.category, HassetteBlockingIOWarning) for w in caught), (
            "IGNORE behavior should suppress the warning"
        )


class TestRaiseBeforeSleep:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_dev_mode_raises_before_sleep(self) -> None:
        """In dev_mode with filterwarnings('error'), time.sleep RAISES before sleeping.

        The test verifies the sleep does not execute by checking elapsed time is tiny
        (well under the 0.05s we'd pass to sleep if it ran).
        """
        tid = threading.get_ident()
        h = make_hassette(dev_mode=True)
        ex = make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        # Use a large nominal duration so "did the real sleep run?" has a wide, load-proof margin:
        # if the guard intercepts, elapsed is only warning-machinery overhead; if it does not, elapsed
        # is ~SLEEP_S. A 0.5s bound separates the two by an order of magnitude even on a loaded CI
        # runner (tight bounds near the sleep duration flaked here repeatedly under xdist + coverage).
        sleep_s = 2.0
        start = time.monotonic()
        with warnings.catch_warnings():
            warnings.filterwarnings("error", category=HassetteBlockingIOWarning)
            with pytest.raises(HassetteBlockingIOWarning):
                time.sleep(sleep_s)  # noqa: ASYNC251 — intentional: guard raises BEFORE this sleep runs
        elapsed = time.monotonic() - start

        assert elapsed < 0.5, f"Sleep appears to have run (elapsed={elapsed:.4f}s); guard did not intercept"

    def test_record_blocking_event_called_before_intercepting_raise(self) -> None:
        """Persist fires BEFORE the warning, so a filterwarnings('error') intercept still records.

        Regression: previously _detect emitted (and raised) before calling record_blocking_event,
        so an intercepting raise skipped the row entirely.
        """
        tid = threading.get_ident()
        h = make_hassette(dev_mode=True)
        ex = make_executor()
        ex.record_blocking_event = MagicMock()
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings():
            warnings.filterwarnings("error", category=HassetteBlockingIOWarning)
            with pytest.raises(HassetteBlockingIOWarning):
                time.sleep(0)  # raises (intercept) after the row is queued

        ex.record_blocking_event.assert_called_once()

    def test_prod_without_flag_no_patch(self) -> None:
        """Production default → time.sleep is NOT patched at all."""
        h = make_hassette(dev_mode=False, allow_deep_detection_in_prod=False)
        ex = make_executor()
        install(h, loop_thread_id=threading.get_ident(), executor=ex)

        # Confirm not installed — primitive is unchanged.
        assert not is_installed()
        assert time.sleep is _REAL_SLEEP

        # A call on the "loop thread" does not fire (nothing is patched).
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        assert not any(issubclass(w.category, HassetteBlockingIOWarning) for w in caught)

    def test_intercepted_framework_io_does_not_escalate_under_suite_config(self) -> None:
        """A guard interception on the loop thread must NOT be escalated to a fatal error by the
        suite's filterwarnings config.

        Under pytest the event loop runs on the main thread, so while the guard is installed an
        open()/socket call made by pytest, coverage, or xdist's execnet transport on that thread is
        intercepted. With the suite-wide ``filterwarnings=["error"]`` and no per-category exception,
        that interception raised HassetteBlockingIOWarning inside framework code and crashed xdist
        workers. This test sets NO local filter — it relies on the suite default — so it fails (the
        open() raises) without the ``default::HassetteBlockingIOWarning`` exception in pyproject.
        """
        h = make_hassette(dev_mode=True)
        ex = make_executor()
        install(h, loop_thread_id=threading.get_ident(), executor=ex)
        try:
            # builtins.open is patched and we are on the loop thread — exactly what coverage /
            # linecache / pytest do. Must emit a (non-fatal) warning and proceed, never raise.
            with open(__file__) as f:
                first = f.readline()
        finally:
            uninstall()

        assert first, "open() should have read the file rather than being escalated to an error"


class TestReentrancyGuard:
    def test_warning_display_reading_source_does_not_recurse(self, tmp_path: Path) -> None:
        """A patched primitive whose warning display opens a file must not recurse — CRITICAL.

        Production reproduces this via linecache: warnings.warn → _formatwarnmsg → linecache
        → tokenize.open → builtins.open (patched) → would re-enter the wrapper forever. The
        per-thread re-entrancy guard makes the inner open pass straight through.
        """
        tid = threading.get_ident()
        h = make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        src_file = tmp_path / "src.py"
        src_file.write_text("x = 1\n")
        inner_open_calls = 0

        def custom_showwarning(*_args, **_kwargs) -> None:
            # Stand in for the real formatter reading a source line — on the loop thread,
            # through the patched builtins.open. Without the guard this recurses to death.
            nonlocal inner_open_calls
            inner_open_calls += 1
            with open(src_file) as fh:  # patched open; must pass through, not re-enter
                fh.read()

        with warnings.catch_warnings():
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            warnings.showwarning = custom_showwarning
            time.sleep(0)  # fires the warning → custom_showwarning → open → must not recurse

        # If we reach here, no RecursionError. The inner open fired once (no nesting).
        assert inner_open_calls == 1

    def test_reentrant_call_passes_through_without_warning(self) -> None:
        """While the guard is active (mid-detection), a patched call passes through unflagged."""
        tid = threading.get_ident()
        h = make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        guard_mod._in_wrapper.active = True
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", HassetteBlockingIOWarning)
                time.sleep(0)
            assert not any(issubclass(w.category, HassetteBlockingIOWarning) for w in caught), (
                "Re-entrant call should pass through without emitting a warning"
            )
        finally:
            guard_mod._in_wrapper.active = False


class TestMonkeypatchEvent:
    def test_event_is_frozen_dataclass(self) -> None:
        """MonkeypatchEvent is a frozen dataclass — direct attribute assignment raises."""
        event = MonkeypatchEvent(
            primitive="time.sleep",
            source_location="app.py:42",
            app_key="my_app",
            instance_name=None,
            instance_index=0,
            execution_id="exec-1",
            tier="monkeypatch",
            detected_at=1.0,
            reason="attributed",
        )
        with pytest.raises((AttributeError, TypeError)):
            event.primitive = "changed"  # pyright: ignore[reportAttributeAccessIssue]

    def test_event_has_required_fields(self) -> None:
        """MonkeypatchEvent has all the fields needed for blocking event persistence."""
        field_names = {f.name for f in fields(MonkeypatchEvent)}
        assert "primitive" in field_names
        assert "source_location" in field_names
        assert "app_key" in field_names
        assert "instance_name" in field_names
        assert "instance_index" in field_names
        assert "execution_id" in field_names
        assert "tier" in field_names
        assert "detected_at" in field_names
        assert "reason" in field_names

    def test_event_tier_is_monkeypatch(self) -> None:
        """MonkeypatchEvent tier is always 'monkeypatch' for Tier 2 events."""
        event = MonkeypatchEvent(
            primitive="os.listdir",
            source_location="app.py:10",
            app_key=None,
            instance_name=None,
            instance_index=None,
            execution_id=None,
            tier="monkeypatch",
            detected_at=2.0,
            reason="framework",
        )
        assert event.tier == "monkeypatch"

    def test_event_populated_on_warning(self) -> None:
        """The warning message includes the primitive name and app key."""
        tid = threading.get_ident()
        h = make_hassette()
        ex = make_executor(app_key="my_cool_app")
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        assert caught, "Expected a warning"
        msg = str(caught[0].message)
        assert "time.sleep" in msg
        assert "my_cool_app" in msg
        assert "monkeypatch" in msg.lower() or "Tier 2" in msg

    def test_unknown_app_uses_framework_label(self) -> None:
        """When marker has no app_key, the warning labels it <framework>."""
        tid = threading.get_ident()
        h = make_hassette()
        ex = make_executor(app_key=None)
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        assert caught
        msg = str(caught[0].message)
        assert "<framework>" in msg


class TestTier2TaskIdentityAttribution:
    """The task_id check withholds attribution only when a *different* task displaced the marker.

    Issue #1048: under concurrent load the single-slot marker can name an execution that yielded
    while another task makes the blocking call. Tier 2 reads the marker inline, so it compares the
    current task against the marker's task to confirm the call is inside the bound execution.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_same_task_call_is_attributed(self) -> None:
        """A call from the task that bound the marker is attributed to its app, reason=attributed."""
        tid = threading.get_ident()
        h = make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = MagicMock()
        ex.record_blocking_event = MagicMock()
        task = asyncio.current_task()
        ex.current_execution = ExecutionMarker(
            app_key="my_app",
            instance_name=None,
            execution_id="exec-attr",
            started_at=time.monotonic(),
            instance_index=0,
            task_id=id(task),
        )
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)  # noqa: ASYNC251 — patched; the guard fires before the real sleep

        msgs = [str(w.message) for w in caught if issubclass(w.category, HassetteBlockingIOWarning)]
        assert msgs
        assert "my_app" in msgs[0]
        event = ex.record_blocking_event.call_args[0][0]
        assert event.app_key == "my_app"
        assert event.reason == "attributed"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_marker_without_task_id_is_trusted(self) -> None:
        """A marker bound outside any task (task_id=None) is trusted by Tier 2 — the deliberate
        asymmetry with Tier 1, which withholds in the same case (it reads cross-thread, Tier 2 reads
        inline in the blocker's own call chain).
        """
        tid = threading.get_ident()
        h = make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = MagicMock()
        ex.record_blocking_event = MagicMock()
        ex.current_execution = ExecutionMarker(
            app_key="my_app",
            instance_name=None,
            execution_id="exec-no-task",
            started_at=time.monotonic(),
            instance_index=0,
            task_id=None,
        )
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)  # noqa: ASYNC251 — patched; the guard fires before the real sleep

        msgs = [str(w.message) for w in caught if issubclass(w.category, HassetteBlockingIOWarning)]
        assert msgs
        assert "my_app" in msgs[0]
        event = ex.record_blocking_event.call_args[0][0]
        assert event.app_key == "my_app"
        assert event.reason == "attributed"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_displaced_call_is_not_attributed_to_innocent_app(self) -> None:
        """A call from a task other than the marker's withholds attribution (NULL, reason=displaced).

        Models the bug: an app bound the marker, yielded, and a different task made the blocking
        call. The innocent app must not be blamed — the row records NULL with reason='displaced'.
        """
        tid = threading.get_ident()
        h = make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = MagicMock()
        ex.record_blocking_event = MagicMock()
        # task_id of a DIFFERENT task than the one running this test — id() is never negative,
        # so -1 can never match the current task and reliably models displacement.
        ex.current_execution = ExecutionMarker(
            app_key="innocent_app",
            instance_name=None,
            execution_id="exec-displaced",
            started_at=time.monotonic(),
            instance_index=0,
            task_id=-1,
        )
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)  # noqa: ASYNC251 — patched; the guard fires before the real sleep

        msgs = [str(w.message) for w in caught if issubclass(w.category, HassetteBlockingIOWarning)]
        assert msgs, "Expected a warning even when attribution is withheld"
        assert "innocent_app" not in msgs[0]
        assert "<framework>" in msgs[0]
        event = ex.record_blocking_event.call_args[0][0]
        assert event.app_key is None
        assert event.execution_id is None
        assert event.reason == "displaced"


class TestSocketMethodPatch:
    def test_socket_connect_on_loop_thread_warns(self) -> None:
        """socket.socket.connect on loop thread triggers warning."""
        tid = threading.get_ident()
        h = make_hassette()
        ex = make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        assert guard_mod._originals.get("socket.socket.connect") is not None

        # Call through the wrapper — the original will fail on a dummy address,
        # but the warning fires before that.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            try:
                sock = socket.socket()
                sock.connect(("127.0.0.1", 1))  # fails to connect; warning fires first
            except (OSError, ConnectionRefusedError):
                pass  # expected — no server; the warning is what matters
            finally:
                with contextlib.suppress(Exception):
                    sock.close()

        msgs = [str(w.message) for w in caught if issubclass(w.category, HassetteBlockingIOWarning)]
        assert msgs, "Expected HassetteBlockingIOWarning for socket.connect on loop thread"
        assert "socket.socket.connect" in msgs[0]
