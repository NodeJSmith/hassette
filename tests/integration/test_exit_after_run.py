"""``hassette run``'s exit check at a real process exit (spec 141 D3).

Each case runs ``exit_child.py`` in a subprocess on the interpreter running the suite, so CI's per-Python
``tests`` sessions prove it on every supported Python. The exit budget is shortened, and the watchdog fires
``EXIT_WATCHDOG_MARGIN_SECONDS`` (set to 0.3s by the child) after it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from hassette.server import EX_SOFTWARE
from tests.support.helpers import EXIT_TASK_SURVIVOR_ERROR, EXIT_WATCHDOG_ERROR

CHILD = Path(__file__).with_name("exit_child.py")
BUDGET_SECONDS = 0.5
HANG_SECONDS = 20.0
"""Far past any expected exit; a child still running then failed to exit at all."""


def run_child(scenario: str, budget: float = BUDGET_SECONDS) -> tuple[int, str]:
    """Run one scenario; return its exit code and its stderr."""
    proc = subprocess.run(
        [sys.executable, str(CHILD), scenario, str(budget)],
        capture_output=True,
        text=True,
        timeout=HANG_SECONDS,
        check=False,
    )
    return proc.returncode, proc.stderr


def test_a_clean_exit_exits_zero_without_an_error() -> None:
    code, err = run_child("clean")

    assert code == 0
    assert "ERROR" not in err


@pytest.mark.parametrize(
    ("scenario", "code", "fatal"), [("swallowing_task", EX_SOFTWARE, False), ("swallowing_task_fatal", 1, True)]
)
def test_a_surviving_task_is_named_and_the_process_hard_exits(scenario: str, code: int, fatal: bool) -> None:
    """A task that swallows its cancellation is named by the task check, before the watchdog could fire."""
    actual, err = run_child(scenario)

    assert actual == code
    assert EXIT_TASK_SURVIVOR_ERROR in err
    assert "swallower" in err
    assert EXIT_WATCHDOG_ERROR not in err
    assert ("Hassette is exiting after an error" in err) == fatal


@pytest.mark.parametrize(("scenario", "code"), [("stuck_thread", EX_SOFTWARE), ("stuck_thread_fatal", 1)])
def test_a_stuck_non_daemon_thread_is_named_with_its_stack_and_the_watchdog_exits(scenario: str, code: int) -> None:
    actual, err = run_child(scenario)

    assert actual == code
    assert EXIT_WATCHDOG_ERROR in err
    assert "Thread[user-device-client] is still running at shutdown" in err
    assert "Thread[MainThread] is still running at shutdown" in err


@pytest.mark.parametrize("scenario", ["daemon_thread", "idle_anyio", "idle_stdlib_pool"])
def test_threads_that_never_hold_exit_never_fire_the_watchdog(scenario: str) -> None:
    code, err = run_child(scenario)

    assert code == 0
    assert "ERROR" not in err


def test_a_stuck_worker_in_a_pool_nobody_shut_down_is_named_without_holding_exit() -> None:
    code, err = run_child("stuck_stdlib_pool")

    assert code == EX_SOFTWARE
    assert EXIT_WATCHDOG_ERROR in err
    assert "Thread[user-pool_0] is still running at shutdown" in err


@pytest.mark.parametrize(
    ("scenario", "blocked_in"), [("frozen_loop", "block_in_cancellation_cleanup"), ("hung_atexit", "hang_at_exit")]
)
def test_a_frozen_loop_or_hung_atexit_handler_ends_by_the_watchdog_with_the_main_threads_stack(
    scenario: str, blocked_in: str
) -> None:
    code, err = run_child(scenario)

    assert code == EX_SOFTWARE
    assert EXIT_WATCHDOG_ERROR in err
    main_stack = err[err.index("Thread[MainThread] is still running at shutdown") :]
    assert blocked_in in main_stack.split("is still running at shutdown")[1]


def test_a_task_that_takes_a_second_to_finish_its_cancellation_exits_zero_without_an_error() -> None:
    """Uses the real exit budget: about 1s of cleanup is well within it."""
    code, err = run_child("slow_cancellation", budget=5.0)

    assert code == 0
    assert "ERROR" not in err


def test_a_task_whose_cancellation_cleanup_raises_is_reported_at_warning_without_a_hard_exit() -> None:
    """The cleanup's error is not lost: asyncio.run() never sees it, so the exit check is its only report."""
    code, err = run_child("raising_cleanup")

    assert code == 0
    assert "WARNING Task raiser raised during the exit cancellation" in err
    assert "RuntimeError: flush failed" in err
    assert "ERROR" not in err


def test_the_shutdown_snapshot_is_waited_for_not_cancelled() -> None:
    code, err = run_child("snapshot")

    assert code == 0
    assert "snapshot written" in err
    assert "ERROR" not in err
