"""Subprocess regression tests for the sync facade generator in --check mode.

These tests invoke the generator as a subprocess and assert exit code 0 — the
same check that CI's ``git diff --exit-code`` step performs, but surfaced as a
local pytest failure. They act as the bridge between the deleted
``test_recording_sync_facade_drift.py`` and the CI gate, so drift is caught on
every local ``pytest`` run without requiring a push.
"""

import subprocess
from pathlib import Path

import pytest

# Repo root is three parents up from this file:
#   tests/unit/test_recording_sync_facade_generation.py
#   → tests/unit/ → tests/ → <repo-root>
_REPO_ROOT = Path(__file__).resolve().parents[2]

GENERATOR_TIMEOUT_SECONDS = 60


def run_generator_check(target: str) -> subprocess.CompletedProcess[str]:
    """Invoke the generator in --check mode for the given target.

    Raises ``pytest.fail`` with a readable remediation hint if the subprocess
    hangs past the timeout — a bare ``subprocess.TimeoutExpired`` is an opaque
    stack trace that doesn't tell the developer what went wrong or how to
    reproduce it manually.
    """
    try:
        return subprocess.run(
            ["uv", "run", "python", "codegen/src/hassette_codegen/sync_facade/", "--target", target, "--check"],
            cwd=_REPO_ROOT,
            capture_output=True,
            timeout=GENERATOR_TIMEOUT_SECONDS,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        # exc.stderr / exc.stdout are partial captures when the process is killed;
        # both can be None if the process timed out before producing any output.
        pytest.fail(
            f"Generator --target {target} --check timed out after {GENERATOR_TIMEOUT_SECONDS}s "
            f"— it may be in an infinite loop or blocked on a subprocess call.\n"
            f"Reproduce manually:\n"
            f"  uv run python codegen/src/hassette_codegen/sync_facade/ --target {target} --check\n\n"
            f"--- captured stderr ---\n{exc.stderr or '(no output captured)'}\n"
            f"--- captured stdout ---\n{exc.stdout or '(no output captured)'}"
        )


# The "api" target also guards against ruff-pipeline divergence (discovered via a prior isort gap).
@pytest.mark.parametrize("target", ["recording", "api", "bus", "scheduler"])
def test_generator_check_mode_exits_zero(target: str) -> None:
    """Generator --target <target> --check exits 0 when the generated file is current."""
    result = run_generator_check(target)
    assert result.returncode == 0, (
        f"Generator --target {target} --check exited non-zero — generated file has drifted.\n"
        "Re-run locally to update it:\n"
        f"  uv run python codegen/src/hassette_codegen/sync_facade/ --target {target}\n\n"
        f"--- stderr ---\n{result.stderr}\n"
        f"--- stdout ---\n{result.stdout}"
    )
