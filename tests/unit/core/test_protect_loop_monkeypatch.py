"""Unit tests for the Tier 2 protect-loop monkeypatch (T04).

Covers:
    FR#5  — each patched primitive responds per behavior before the call proceeds
    FR#8/AC#4  — off-loop calls pass through unflagged
    FR#6/AC#10 — enablement matrix: dev→ON, prod default→OFF, prod+flag→ON
    FR#12/AC#9 — idempotent install; uninstall restores originals; re-install is clean
    AC#5  — dev_mode + filterwarnings("error") causes loop-thread time.sleep to RAISE
            BEFORE sleeping (the sleep never happens); prod without flag → no patch
    MonkeypatchEvent — dataclass fields are populated correctly
"""

import builtins
import contextlib
import glob as glob_module
import os
import socket
import threading
import time
import warnings
from dataclasses import fields
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REAL_SLEEP = time.__dict__["sleep"]  # stash before any test mutates time.sleep
_REAL_OPEN = builtins.__dict__["open"]


def _make_hassette(
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


def _make_executor(*, app_key: str | None = "test_app", instance_index: int | None = 0) -> MagicMock:
    executor = MagicMock()
    executor.current_execution = ExecutionMarker(
        app_key=app_key,
        instance_name=None,
        execution_id="exec-t04",
        started_at=time.monotonic(),
        instance_index=instance_index,
    )
    return executor


# ---------------------------------------------------------------------------
# Guaranteed-teardown fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def ensure_uninstall():
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


# ---------------------------------------------------------------------------
# FR#6 / AC#10 — enablement matrix
# ---------------------------------------------------------------------------


class TestEnablementMatrix:
    def test_dev_mode_installs(self):
        """dev_mode=True → Tier 2 installs."""
        h = _make_hassette(dev_mode=True)
        ex = _make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is True
        assert is_installed()
        assert time.sleep is not _REAL_SLEEP

    def test_prod_default_does_not_install(self):
        """Production without flag → NOT patched (AC#10)."""
        h = _make_hassette(dev_mode=False, allow_deep_detection_in_prod=False)
        ex = _make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is False
        assert not is_installed()
        assert time.sleep is _REAL_SLEEP

    def test_prod_with_flag_and_explicit_enabled_installs(self):
        """Production with deep_detection_enabled=True + allow_deep_detection_in_prod=True → patched.

        The enablement spec: deep_detection_enabled=None → follows dev_mode. With dev_mode=False
        that yields enabled=False → returns False early. To reach the prod flag check, the operator
        must set deep_detection_enabled=True explicitly; the prod gate then gates on
        allow_deep_detection_in_prod.
        """
        h = _make_hassette(dev_mode=False, deep_detection_enabled=True, allow_deep_detection_in_prod=True)
        ex = _make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is True
        assert is_installed()
        assert time.sleep is not _REAL_SLEEP

    def test_explicit_disabled_overrides_dev_mode(self):
        """deep_detection_enabled=False overrides dev_mode=True."""
        h = _make_hassette(dev_mode=True, deep_detection_enabled=False)
        ex = _make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is False
        assert not is_installed()
        assert time.sleep is _REAL_SLEEP

    def test_explicit_enabled_prod_no_allow_flag_not_installed(self):
        """deep_detection_enabled=True in prod without allow flag → NOT installed (prod gate applies).

        Flow:
            enabled = True (not None)
            if not enabled: return False   # skip
            if dev_mode: return True       # False → continue
            return allow_deep_detection_in_prod  # False → NOT installed
        """
        h = _make_hassette(dev_mode=False, deep_detection_enabled=True, allow_deep_detection_in_prod=False)
        ex = _make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is False
        assert not is_installed()

    def test_explicit_enabled_prod_with_allow_flag(self):
        """deep_detection_enabled=True + prod + allow flag → installed."""
        h = _make_hassette(dev_mode=False, deep_detection_enabled=True, allow_deep_detection_in_prod=True)
        ex = _make_executor()
        result = install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert result is True
        assert is_installed()


# ---------------------------------------------------------------------------
# FR#12 / AC#9 — idempotency and leak prevention
# ---------------------------------------------------------------------------


class TestIdempotencyAndLeak:
    def test_double_install_is_noop(self):
        """Second install without uninstall is a no-op (returns False)."""
        h = _make_hassette()
        ex = _make_executor()
        tid = threading.get_ident()
        first = install(h, loop_thread_id=tid, executor=ex)
        second = install(h, loop_thread_id=tid, executor=ex)
        assert first is True
        assert second is False  # no-op

    def test_uninstall_when_not_installed_is_noop(self):
        """uninstall() when not installed returns False and does not raise."""
        result = uninstall()
        assert result is False

    def test_uninstall_restores_time_sleep(self):
        """After uninstall, time.sleep is the original."""
        h = _make_hassette()
        ex = _make_executor()
        install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert time.sleep is not _REAL_SLEEP
        uninstall()
        assert time.sleep is _REAL_SLEEP

    def test_uninstall_restores_builtins_open(self):
        """After uninstall, builtins.open is the original."""
        h = _make_hassette()
        ex = _make_executor()
        install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert builtins.open is not _REAL_OPEN
        uninstall()
        assert builtins.open is _REAL_OPEN

    def test_uninstall_restores_all_primitives(self):
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
        h = _make_hassette()
        ex = _make_executor()
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

    def test_reinstall_after_uninstall_works(self):
        """After uninstall, a re-install succeeds and patches primitives again."""
        h = _make_hassette()
        ex = _make_executor()
        tid = threading.get_ident()
        install(h, loop_thread_id=tid, executor=ex)
        uninstall()
        assert time.sleep is _REAL_SLEEP
        second = install(h, loop_thread_id=tid, executor=ex)
        assert second is True
        assert time.sleep is not _REAL_SLEEP

    def test_is_installed_reflects_state(self):
        """is_installed() tracks install/uninstall state correctly."""
        assert not is_installed()
        h = _make_hassette()
        ex = _make_executor()
        install(h, loop_thread_id=threading.get_ident(), executor=ex)
        assert is_installed()
        uninstall()
        assert not is_installed()


# ---------------------------------------------------------------------------
# FR#8 / AC#4 — off-loop thread gate: never flag calls from worker threads
# ---------------------------------------------------------------------------


class TestOffLoopGate:
    def test_time_sleep_off_loop_thread_passes_through(self):
        """time.sleep called from a worker thread is not flagged (FR#8/AC#4)."""
        fake_loop_thread_id = threading.get_ident() + 9999  # different from current thread
        h = _make_hassette()
        ex = _make_executor()
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

    def test_loop_thread_call_fires_warning(self):
        """time.sleep on the loop thread (our thread) triggers warning."""
        tid = threading.get_ident()
        h = _make_hassette()
        ex = _make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        assert any(issubclass(w.category, HassetteBlockingIOWarning) for w in caught), (
            "Expected HassetteBlockingIOWarning on loop-thread time.sleep"
        )


# ---------------------------------------------------------------------------
# FR#5 — per-primitive WARN / IGNORE / ERROR behaviors
# ---------------------------------------------------------------------------


class TestPrimitiveWarnBehavior:
    def test_time_sleep_loop_thread_warns(self):
        """time.sleep on loop thread emits HassetteBlockingIOWarning (WARN behavior)."""
        tid = threading.get_ident()
        h = _make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = _make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        msgs = [str(w.message) for w in caught if issubclass(w.category, HassetteBlockingIOWarning)]
        assert msgs, "Expected a HassetteBlockingIOWarning for time.sleep on loop thread"
        assert "time.sleep" in msgs[0]
        assert "test_app" in msgs[0]

    def test_open_loop_thread_warns(self, tmp_path):
        """builtins.open on loop thread emits HassetteBlockingIOWarning (WARN behavior)."""
        tid = threading.get_ident()
        h = _make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = _make_executor()
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

    def test_ignore_behavior_suppresses_warning(self):
        """IGNORE behavior → no warning, original is still called."""
        tid = threading.get_ident()
        h = _make_hassette(behavior=BlockingIOBehavior.IGNORE)
        ex = _make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        # Wire h.hassette.config.blocking_io.behavior so resolver reads IGNORE.
        h.hassette.config.blocking_io.behavior = BlockingIOBehavior.IGNORE

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        assert not any(issubclass(w.category, HassetteBlockingIOWarning) for w in caught), (
            "IGNORE behavior should suppress the warning"
        )


# ---------------------------------------------------------------------------
# AC#5 — dev_mode RAISES before sleep; prod without flag → no patch
# ---------------------------------------------------------------------------


class TestRaiseBeforeSleep:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_dev_mode_raises_before_sleep(self):
        """In dev_mode with filterwarnings('error'), time.sleep RAISES before sleeping.

        The test verifies the sleep does not execute by checking elapsed time is tiny
        (well under the 0.05s we'd pass to sleep if it ran).
        """
        tid = threading.get_ident()
        h = _make_hassette(dev_mode=True)
        ex = _make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        start = time.monotonic()
        with warnings.catch_warnings():
            warnings.filterwarnings("error", category=HassetteBlockingIOWarning)
            with pytest.raises(HassetteBlockingIOWarning):
                time.sleep(0.05)  # noqa: ASYNC251 — intentional: guard raises BEFORE this sleep runs
        elapsed = time.monotonic() - start

        # If sleep actually ran, elapsed would be ≥ 0.05s.
        # The guard raises BEFORE the call, so elapsed should be tiny.
        assert elapsed < 0.03, f"Sleep appears to have run (elapsed={elapsed:.4f}s); guard did not intercept"

    def test_record_blocking_event_called_before_intercepting_raise(self):
        """Persist fires BEFORE the warning, so a filterwarnings('error') intercept still records.

        Regression: previously _detect emitted (and raised) before calling record_blocking_event,
        so an intercepting raise skipped the row entirely.
        """
        tid = threading.get_ident()
        h = _make_hassette(dev_mode=True)
        ex = _make_executor()
        ex.record_blocking_event = MagicMock()
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings():
            warnings.filterwarnings("error", category=HassetteBlockingIOWarning)
            with pytest.raises(HassetteBlockingIOWarning):
                time.sleep(0)  # raises (intercept) after the row is queued

        ex.record_blocking_event.assert_called_once()

    def test_prod_without_flag_no_patch(self):
        """Production default → time.sleep is NOT patched at all."""
        h = _make_hassette(dev_mode=False, allow_deep_detection_in_prod=False)
        ex = _make_executor()
        install(h, loop_thread_id=threading.get_ident(), executor=ex)

        # Confirm not installed — primitive is unchanged.
        assert not is_installed()
        assert time.sleep is _REAL_SLEEP

        # A call on the "loop thread" does not fire (nothing is patched).
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        assert not any(issubclass(w.category, HassetteBlockingIOWarning) for w in caught)


# ---------------------------------------------------------------------------
# Re-entrancy guard — emitting a warning must not recurse through patched open
# ---------------------------------------------------------------------------


class TestReentrancyGuard:
    def test_warning_display_reading_source_does_not_recurse(self, tmp_path):
        """A patched primitive whose warning display opens a file must not recurse — CRITICAL.

        Production reproduces this via linecache: warnings.warn → _formatwarnmsg → linecache
        → tokenize.open → builtins.open (patched) → would re-enter the wrapper forever. The
        per-thread re-entrancy guard makes the inner open pass straight through.
        """
        tid = threading.get_ident()
        h = _make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = _make_executor()
        install(h, loop_thread_id=tid, executor=ex)

        src_file = tmp_path / "src.py"
        src_file.write_text("x = 1\n")
        inner_open_calls = 0

        def custom_showwarning(*_args, **_kwargs):
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

    def test_reentrant_call_passes_through_without_warning(self):
        """While the guard is active (mid-detection), a patched call passes through unflagged."""
        tid = threading.get_ident()
        h = _make_hassette(behavior=BlockingIOBehavior.WARN)
        ex = _make_executor()
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


# ---------------------------------------------------------------------------
# MonkeypatchEvent structure
# ---------------------------------------------------------------------------


class TestMonkeypatchEvent:
    def test_event_is_frozen_dataclass(self):
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
        )
        with pytest.raises((AttributeError, TypeError)):
            event.primitive = "changed"  # pyright: ignore[reportAttributeAccessIssue]

    def test_event_has_required_fields(self):
        """MonkeypatchEvent has all the fields T05 needs."""
        field_names = {f.name for f in fields(MonkeypatchEvent)}
        assert "primitive" in field_names
        assert "source_location" in field_names
        assert "app_key" in field_names
        assert "instance_name" in field_names
        assert "instance_index" in field_names
        assert "execution_id" in field_names
        assert "tier" in field_names
        assert "detected_at" in field_names

    def test_event_tier_is_monkeypatch(self):
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
        )
        assert event.tier == "monkeypatch"

    def test_event_populated_on_warning(self):
        """The warning message includes the primitive name and app key."""
        tid = threading.get_ident()
        h = _make_hassette()
        ex = _make_executor(app_key="my_cool_app")
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        assert caught, "Expected a warning"
        msg = str(caught[0].message)
        assert "time.sleep" in msg
        assert "my_cool_app" in msg
        assert "monkeypatch" in msg.lower() or "Tier 2" in msg

    def test_unknown_app_uses_framework_label(self):
        """When marker has no app_key, the warning labels it <framework>."""
        tid = threading.get_ident()
        h = _make_hassette()
        ex = _make_executor(app_key=None)
        install(h, loop_thread_id=tid, executor=ex)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", HassetteBlockingIOWarning)
            time.sleep(0)

        assert caught
        msg = str(caught[0].message)
        assert "<framework>" in msg


# ---------------------------------------------------------------------------
# Socket method patching (method wrapper)
# ---------------------------------------------------------------------------


class TestSocketMethodPatch:
    def test_socket_connect_on_loop_thread_warns(self):
        """socket.socket.connect on loop thread triggers warning."""
        tid = threading.get_ident()
        h = _make_hassette()
        ex = _make_executor()
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
