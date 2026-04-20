"""Unit tests for RegistrationTracker.

Tests verify:
- prune_and_track stores tasks
- Completed tasks are pruned on next prune_and_track
- await_complete returns immediately for unknown key
- await_complete awaits pending tasks
- await_complete logs warning on timeout with non-zero incomplete count (AC #10)
- await_complete cancels stragglers on timeout
- drain_framework_keys iterates framework-prefixed keys
"""

import asyncio
import contextlib
from unittest.mock import MagicMock

from hassette.core.registration_tracker import RegistrationTracker
from hassette.types.types import FRAMEWORK_APP_KEY, FRAMEWORK_APP_KEY_PREFIX


def _make_tracker() -> RegistrationTracker:
    return RegistrationTracker()


class TestPruneAndTrack:
    async def test_track_adds_task(self) -> None:
        """prune_and_track stores the task under the given app_key."""
        tracker = _make_tracker()

        async def _noop() -> None:
            pass

        task = asyncio.create_task(_noop())
        tracker.prune_and_track("my_app", task)

        assert task in tracker._tasks["my_app"]
        await task

    async def test_prune_removes_done_tasks(self) -> None:
        """Completed tasks are pruned on next prune_and_track call."""
        tracker = _make_tracker()

        async def _noop() -> None:
            pass

        done_task = asyncio.create_task(_noop())
        await done_task  # complete it

        tracker._tasks["my_app"].append(done_task)
        assert done_task.done()

        # Add a new task — the done one should be pruned
        new_task = asyncio.create_task(_noop())
        tracker.prune_and_track("my_app", new_task)

        assert done_task not in tracker._tasks["my_app"]
        assert new_task in tracker._tasks["my_app"]
        await new_task


class TestAwaitComplete:
    async def test_returns_immediately_for_unknown_key(self) -> None:
        """No-op for a key with no tracked tasks."""
        tracker = _make_tracker()
        logger = MagicMock()
        # Should complete without raising
        await tracker.await_complete("nonexistent_app", timeout=30.0, logger=logger)
        logger.warning.assert_not_called()

    async def test_awaits_pending_tasks(self) -> None:
        """Tasks complete within timeout."""
        tracker = _make_tracker()
        logger = MagicMock()
        completed = asyncio.Event()

        async def _work() -> None:
            completed.set()

        task = asyncio.create_task(_work())
        tracker.prune_and_track("my_app", task)

        await tracker.await_complete("my_app", timeout=5.0, logger=logger)

        assert completed.is_set()
        logger.warning.assert_not_called()

    async def test_logs_warning_on_timeout(self) -> None:
        """Incomplete count is non-zero in warning message (AC #10)."""
        tracker = _make_tracker()
        logger = MagicMock()

        gate = asyncio.Event()

        async def _blocked() -> None:
            await gate.wait()

        task = asyncio.create_task(_blocked())
        tracker.prune_and_track("my_app", task)

        try:
            await tracker.await_complete("my_app", timeout=0.01, logger=logger)
        finally:
            gate.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        logger.warning.assert_called_once()
        warning_args = logger.warning.call_args[0]
        warning_msg = warning_args[0]
        assert "timed out" in warning_msg
        # AC #10: incomplete count must be non-zero
        # The count is passed as a positional arg to the format string
        incomplete_count = warning_args[3]
        assert incomplete_count > 0, "Incomplete count must be non-zero at timeout"

    async def test_cancels_stragglers(self) -> None:
        """Timed-out tasks are cancelled."""
        tracker = _make_tracker()
        logger = MagicMock()

        gate = asyncio.Event()

        async def _blocked() -> None:
            await gate.wait()

        task = asyncio.create_task(_blocked())
        tracker.prune_and_track("my_app", task)

        await tracker.await_complete("my_app", timeout=0.01, logger=logger)

        # Let the cancellation propagate
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert task.cancelled()


class TestDrainFrameworkKeys:
    async def test_drain_framework_keys(self) -> None:
        """Iterates framework-prefixed keys and calls await_fn for each."""
        tracker = _make_tracker()
        drained: list[str] = []

        async def fake_await(key: str) -> None:
            drained.append(key)

        # Set up mixed keys
        tracker._tasks["my_app"] = []
        tracker._tasks[FRAMEWORK_APP_KEY] = []
        tracker._tasks[f"{FRAMEWORK_APP_KEY_PREFIX}service_watcher"] = []
        tracker._tasks[f"{FRAMEWORK_APP_KEY_PREFIX}core"] = []

        await tracker.drain_framework_keys(fake_await)

        assert "my_app" not in drained
        assert FRAMEWORK_APP_KEY in drained
        assert f"{FRAMEWORK_APP_KEY_PREFIX}service_watcher" in drained
        assert f"{FRAMEWORK_APP_KEY_PREFIX}core" in drained
