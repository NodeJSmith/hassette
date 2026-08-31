"""Blocking-IO watchdog and monkeypatch-guard mock factories for tests/unit/core/."""

import asyncio
import time
from unittest.mock import MagicMock

from hassette.core.command_executor import ExecutionMarker
from hassette.types.enums import BlockingIOBehavior


def make_blocking_io_hassette(
    *,
    behavior: BlockingIOBehavior | None = None,
    watchdog_enabled: bool = True,
    lag_threshold_seconds: float = 0.10,
    watchdog_interval_seconds: float = 0.25,
    capture_stack_on_block: bool = False,
    dev_mode: bool = True,
    deep_detection_enabled: bool | None = None,
    allow_deep_detection_in_prod: bool = False,
) -> MagicMock:
    """Minimal mock Hassette for blocking-IO guard and watchdog tests."""
    cfg = MagicMock()
    cfg.dev_mode = dev_mode
    cfg.blocking_io.watchdog_enabled = watchdog_enabled
    cfg.blocking_io.lag_threshold_seconds = lag_threshold_seconds
    cfg.blocking_io.watchdog_interval_seconds = watchdog_interval_seconds
    cfg.blocking_io.capture_stack_on_block = capture_stack_on_block
    cfg.blocking_io.deep_detection_enabled = deep_detection_enabled
    cfg.blocking_io.allow_deep_detection_in_prod = allow_deep_detection_in_prod
    cfg.blocking_io.behavior = behavior
    h = MagicMock()
    h.config = cfg
    h.app_handler.get.return_value = None
    # resolve_blocking_io_behavior falls through two hops: per-app → global.
    # None here forces the fallthrough to the global path.
    h.app_config.blocking_io_behavior = None
    h.hassette.config.blocking_io.behavior = behavior
    return h


def make_marker_executor(
    *,
    app_key: str | None = "test_app",
    instance_index: int | None = None,
    stamp_task_id: bool = False,
    execution_id: str = "exec-test",
) -> MagicMock:
    """Build a mock executor with an ExecutionMarker on current_execution.

    For watchdog tests, pass stamp_task_id=True to attribute blocks to the current task.
    For monkeypatch tests, pass instance_index to identify the app instance.
    """
    executor = MagicMock()
    task_id = None
    if stamp_task_id:
        task = asyncio.current_task()
        task_id = id(task) if task is not None else None
    executor.current_execution = ExecutionMarker(
        app_key=app_key,
        instance_name=None,
        execution_id=execution_id,
        started_at=time.monotonic(),
        task_id=task_id,
        instance_index=instance_index,
    )
    return executor
