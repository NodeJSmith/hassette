"""Tests for shutdown-budget allocation and the remaining-time readers in ``hassette.resources.shutdown_budget``."""

import asyncio

import pytest

from hassette.resources import shutdown_budget
from hassette.resources.shutdown_budget import compute_shutdown_budget
from tests.support.mock_hassette import make_mock_hassette

from .conftest import SimpleParent


def test_compute_shutdown_budget_reserves_nonzero_hooks_pool_for_small_timeouts():
    """Regression: a ``resource_shutdown_timeout_seconds`` too small to fit the full tail
    reservation must still leave the hooks pool a nonzero share, scaled down like every other
    stage -- not collapsed to exactly 0. ``LifecycleConfig`` places no lower bound on this
    setting, so a small value (e.g. 2s) is reachable in practice; before this fix, any
    on_shutdown() hook would be cancelled at its very first suspension point regardless of how
    little work it does, because ``asyncio.timeout(0)`` is already expired.
    """
    now = 100.0
    budget = shutdown_budget.compute_shutdown_budget(2.0, now)

    assert budget.hooks_pool_deadline > now, "the hooks pool must not collapse to 0"


def test_compute_shutdown_budget_honors_configured_task_cancel_ceiling():
    """Regression: the task-cancel stage must use the caller-supplied ceiling (in production,
    ``lifecycle.task_cancellation_timeout_seconds``), not a hardcoded 1.0s -- a task that
    cooperatively finishes within the configured allowance but after the old hardcoded second
    was previously reported as ``TASKS_PENDING`` even though it completed on time.
    """
    now = 100.0
    budget = shutdown_budget.compute_shutdown_budget(30.0, now, task_cancel_ceiling=5.0)

    assert budget.task_cancel_seconds == 5.0


async def test_children_budget_remaining_single_wave_returns_floor_when_over_budget():
    """Pin: waves_left=1 (default) returns at least children_floor_seconds, preserving
    Resource._shutdown_children()'s single-batch behavior even when body_deadline has passed.
    """
    loop = asyncio.get_running_loop()
    past_deadline = loop.time() - 5.0
    budget = shutdown_budget.ShutdownBudget(
        hooks_pool_deadline=past_deadline,
        task_cancel_seconds=1.0,
        cleanup_seconds=0.5,
        children_floor_seconds=shutdown_budget.CHILDREN_FLOOR_SECONDS,
        body_deadline=past_deadline,
        total_deadline=loop.time() + 30.0,
    )

    hassette_stub = make_mock_hassette(sealed=False)
    hassette_stub.config.lifecycle.resource_shutdown_timeout_seconds = 30.0
    parent = SimpleParent(hassette_stub)
    parent._shutdown_budget = budget

    result = shutdown_budget.children_budget_remaining(parent)
    assert result == shutdown_budget.CHILDREN_FLOOR_SECONDS


async def test_children_budget_remaining_single_wave_benefits_from_slack():
    """Pin: waves_left=1 (default) returns remaining time when it exceeds the floor."""
    hassette_stub = make_mock_hassette(sealed=False)
    hassette_stub.config.lifecycle.resource_shutdown_timeout_seconds = 30.0

    parent = SimpleParent(hassette_stub)
    loop = asyncio.get_running_loop()
    parent._shutdown_budget = compute_shutdown_budget(30.0, loop.time())

    result = shutdown_budget.children_budget_remaining(parent)
    # Body deadline is ~27s from now (30 - 10% margin), and children floor is 1.0s.
    # The remaining time is much larger than the floor.
    assert result > shutdown_budget.CHILDREN_FLOOR_SECONDS


async def test_children_budget_remaining_multi_wave_divides_across_waves():
    """When waves_left > 1, the remaining time is divided across waves and floored
    at CHILDREN_WAVE_FLOOR_SECONDS, not CHILDREN_FLOOR_SECONDS.
    """
    hassette_stub = make_mock_hassette(sealed=False)
    hassette_stub.config.lifecycle.resource_shutdown_timeout_seconds = 30.0

    parent = SimpleParent(hassette_stub)
    loop = asyncio.get_running_loop()
    parent._shutdown_budget = compute_shutdown_budget(30.0, loop.time())

    remaining = parent._shutdown_budget.body_deadline - loop.time()
    result = shutdown_budget.children_budget_remaining(parent, waves_left=7)
    # Should be approximately remaining / 7, not the full remaining time.
    assert result == pytest.approx(remaining / 7, abs=0.1)


async def test_children_budget_remaining_multi_wave_uses_wave_floor_when_over_budget():
    """When waves_left > 1 and body_deadline has passed, each wave gets at most
    CHILDREN_WAVE_FLOOR_SECONDS (0.1s), not CHILDREN_FLOOR_SECONDS (1.0s).
    """
    hassette_stub = make_mock_hassette(sealed=False)
    hassette_stub.config.lifecycle.resource_shutdown_timeout_seconds = 30.0

    parent = SimpleParent(hassette_stub)
    loop = asyncio.get_running_loop()
    past_deadline = loop.time() - 5.0
    parent._shutdown_budget = shutdown_budget.ShutdownBudget(
        hooks_pool_deadline=past_deadline,
        task_cancel_seconds=1.0,
        cleanup_seconds=0.5,
        children_floor_seconds=1.0,
        body_deadline=past_deadline,
        total_deadline=loop.time() + 30.0,
    )

    result = shutdown_budget.children_budget_remaining(parent, waves_left=7)
    assert result == shutdown_budget.CHILDREN_WAVE_FLOOR_SECONDS
    # Worst-case total overrun from 7 waves: 6 * 0.1 + 1.0 = 1.6s (the final wave
    # falls back to CHILDREN_FLOOR_SECONDS via waves_left=1), well within the
    # 3s margin (10% of 30s).
    worst_case = (7 - 1) * shutdown_budget.CHILDREN_WAVE_FLOOR_SECONDS + shutdown_budget.CHILDREN_FLOOR_SECONDS
    assert worst_case < 30.0 * shutdown_budget.COORDINATOR_MARGIN_FRACTION
