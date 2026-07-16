"""Pyright probe assertion: forgotten-await detection.

Runs pyright on tests/pyright_probes/forgotten_await_probe.py via a dedicated
pyrightconfig that enables reportUnusedCoroutine as an error, then asserts
that every expected diagnostic is present in the output.

This test is a CI gate: if a future annotation change silently kills Pyright's
static detection (e.g. narrowing -> Coroutine[...] to -> Awaitable or a
concrete type), this test fails.

The probe file is excluded from the main pyrightconfig.json (via **/tests
ignore) so it does NOT contribute errors to the normal `uv run pyright` run.

Probe lines are identified via `# PROBE: <label>` end-of-line comments in
forgotten_await_probe.py. The test reads the file at load time, extracts
(lineno, label) pairs, and asserts a reportUnusedCoroutine diagnostic exists
at each extracted line. This avoids brittle hardcoded line numbers.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
PROBE_DIR = WORKTREE_ROOT / "tests" / "pyright_probes"
PROBE_FILE = PROBE_DIR / "forgotten_await_probe.py"

EXPECTED_PROBE_COUNT = 8


def _extract_probe_lines() -> list[tuple[int, str]]:
    """Read probe file and extract (1-based lineno, label) for lines with # PROBE: <label>."""
    pairs = []
    for lineno, line in enumerate(PROBE_FILE.read_text().splitlines(), start=1):
        m = re.search(r"#\s*PROBE:\s*(\S+)", line)
        if m:
            pairs.append((lineno, m.group(1)))
    return pairs


# Extracted at module load time so a missing marker is caught at collection.
PROBE_LINES = _extract_probe_lines()


def test_probe_marker_count() -> None:
    """Guard: probe file must contain exactly EXPECTED_PROBE_COUNT PROBE markers.

    Fails if a marker is accidentally deleted or added without updating this count.
    """
    assert len(PROBE_LINES) == EXPECTED_PROBE_COUNT, (
        f"Expected {EXPECTED_PROBE_COUNT} # PROBE: markers in {PROBE_FILE.name}, "
        f"found {len(PROBE_LINES)}: {PROBE_LINES}.\n"
        f"Update EXPECTED_PROBE_COUNT or restore the missing marker."
    )


def test_pyright_probe_fires_unused_coroutine() -> None:
    """Pyright reports reportUnusedCoroutine on all bare probe calls.

    Covers:
      - Simple bus method: on_state_change
      - Scheduler method:  run_in
      - Overloaded api:    call_service with ServiceResponse overload
      - Overloaded api:    call_service with None overload
      - None-returning:    turn_on
      - Cache method:      get
      - Cache method:      set
      - Cache method:      get_or_set
    """
    try:
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
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("pyright timed out after 120s — check for hung pyright process or very slow CI")

    output = result.stdout + result.stderr

    # Guard: pyright must be installed and runnable.
    if "No module named" in output or "No module named" in result.stderr:
        pytest.fail(
            "pyright is not installed or not runnable as a Python module. "
            "Install it: uv add --dev pyright\n\nOutput:\n" + output
        )

    # Count reportUnusedCoroutine occurrences
    unused_coro_count = output.count("reportUnusedCoroutine")
    assert unused_coro_count >= EXPECTED_PROBE_COUNT, (
        f"Expected at least {EXPECTED_PROBE_COUNT} reportUnusedCoroutine diagnostics, "
        f"got {unused_coro_count}.\n\nPyright output:\n{output}\n\n"
        f"A return annotation may have been changed from Coroutine[...] to Awaitable or a "
        f"concrete type, silently killing Pyright's static detection. See design/071."
    )

    # Verify each probe line is flagged (line number present in output + reportUnusedCoroutine)
    probe_filename = PROBE_FILE.name
    for line_no, label in PROBE_LINES:
        pattern = rf"{re.escape(probe_filename)}:{line_no}:\d+ - error:.*reportUnusedCoroutine"
        assert re.search(pattern, output), (
            f"Expected reportUnusedCoroutine at line {line_no} (PROBE: {label}), "
            f"but no matching diagnostic was found.\n\nPyright output:\n{output}"
        )

    # The probe file must not have ZERO errors — that would mean pyright ran on the
    # wrong file or the probe was accidentally fixed.
    assert result.returncode != 0, (
        "Pyright exited with code 0 on the probe file — expected errors but got none. "
        "The probe file may not have been found, or all bare calls were silently removed."
    )
