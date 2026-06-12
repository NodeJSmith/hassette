"""Pyright probe assertion: forgotten-await detection (FR#5, AC#3).

Runs pyright on tests/pyright_probes/forgotten_await_probe.py via a dedicated
pyrightconfig that enables reportUnusedCoroutine as an error, then asserts
that every expected diagnostic is present in the output.

This test is a CI gate: if a future annotation change silently kills Pyright's
static detection (e.g. narrowing -> Coroutine[...] to -> Awaitable or a
concrete type), this test fails.

The probe file is excluded from the main pyrightconfig.json (via **/tests
ignore) so it does NOT contribute errors to the normal `uv run pyright` run.
"""

import re
import subprocess
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
PROBE_DIR = WORKTREE_ROOT / "tests" / "pyright_probes"
PROBE_FILE = PROBE_DIR / "forgotten_await_probe.py"

# Every bare call in forgotten_await_probe.py that must be flagged.
# Format: (substring_to_match_in_message, description_for_test_failure)
# Pyright reports line:col for each diagnostic — not method names.
# These are the lines in forgotten_await_probe.py where bare calls appear.
# Update if probe file lines change.
EXPECTED_PROBE_LINES = [
    (114, "bus.on_state_change  — simple bus method"),
    (119, "scheduler.run_in  — scheduler method"),
    (122, "api.call_service(None, True)  — ServiceResponse overload"),
    (125, "api.call_service()  — None overload"),
    (128, "api.turn_on()  — None-returning method"),
]
EXPECTED_TOTAL_UNUSED_COROUTINE = len(EXPECTED_PROBE_LINES)


def test_pyright_probe_fires_unused_coroutine() -> None:
    """FR#5/AC#3: pyright reports reportUnusedCoroutine on all bare probe calls.

    Covers:
      - Simple bus method: on_state_change
      - Scheduler method:  run_in
      - Overloaded api:    call_service with ServiceResponse overload
      - Overloaded api:    call_service with None overload
      - None-returning:    turn_on
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pyright",
            "--project",
            str(PROBE_DIR),
        ],
        capture_output=True,
        text=True,
        cwd=str(WORKTREE_ROOT),
    )

    output = result.stdout + result.stderr

    # Count reportUnusedCoroutine occurrences
    unused_coro_count = output.count("reportUnusedCoroutine")
    assert unused_coro_count >= EXPECTED_TOTAL_UNUSED_COROUTINE, (
        f"Expected at least {EXPECTED_TOTAL_UNUSED_COROUTINE} reportUnusedCoroutine diagnostics, "
        f"got {unused_coro_count}.\n\nPyright output:\n{output}\n\n"
        f"A return annotation may have been changed from Coroutine[...] to Awaitable or a "
        f"concrete type, silently killing Pyright's static detection. See design/071 FR#5/AC#3."
    )

    # Verify each probe line is flagged (line number present in output + reportUnusedCoroutine)
    probe_filename = PROBE_FILE.name
    for line_no, description in EXPECTED_PROBE_LINES:
        pattern = rf"{re.escape(probe_filename)}:{line_no}:\d+ - error:.*reportUnusedCoroutine"
        assert re.search(pattern, output), (
            f"Expected reportUnusedCoroutine at line {line_no} ({description}), "
            f"but no matching diagnostic was found.\n\nPyright output:\n{output}"
        )

    # The probe file must not have ZERO errors — that would mean pyright ran on the
    # wrong file or the probe was accidentally fixed.
    assert result.returncode != 0, (
        "Pyright exited with code 0 on the probe file — expected errors but got none. "
        "The probe file may not have been found, or all bare calls were silently removed."
    )
