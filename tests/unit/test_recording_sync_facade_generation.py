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


def test_generator_check_mode_exits_zero() -> None:
    """Generator --target recording --check exits 0 when sync_facade.py is current.

    Fails when ``src/hassette/test_utils/sync_facade.py`` has drifted from its
    sources (``recording_api.py``, ``api.py``, or ``codegen/src/hassette_codegen/sync_facade/``).
    On failure the captured stderr describes what changed.
    """
    result = run_generator_check("recording")
    assert result.returncode == 0, (
        "Generator --target recording --check exited non-zero — sync_facade.py has drifted.\n"
        "Re-run locally to update it:\n"
        "  uv run python codegen/src/hassette_codegen/sync_facade/ --target recording\n\n"
        f"--- stderr ---\n{result.stderr}\n"
        f"--- stdout ---\n{result.stdout}"
    )


def test_generator_check_mode_api_exits_zero() -> None:
    """Generator --target api --check exits 0 when sync.py is current.

    Smoke-tests the existing api-generation path through --check mode. Acts
    as a regression guard against any future change to ``run_ruff()``,
    ``_format_via_ruff()``, or the api-generation pipeline that would cause
    --check to spuriously fail on a current ``src/hassette/api/sync.py``
    (e.g., adding a byte-affecting ruff step on the write path without also
    adding it to the check path, the way the WP02→WP03 isort gap was
    discovered).
    """
    result = run_generator_check("api")
    assert result.returncode == 0, (
        "Generator --target api --check exited non-zero — sync.py has drifted.\n"
        "Re-run locally to update it:\n"
        "  uv run python codegen/src/hassette_codegen/sync_facade/ --target api\n\n"
        f"--- stderr ---\n{result.stderr}\n"
        f"--- stdout ---\n{result.stdout}"
    )


def test_generator_check_mode_bus_exits_zero() -> None:
    """Generator --target bus --check exits 0 when bus/sync.py is current."""
    result = run_generator_check("bus")
    assert result.returncode == 0, (
        "Generator --target bus --check exited non-zero — bus/sync.py has drifted.\n"
        "Re-run locally to update it:\n"
        "  uv run python codegen/src/hassette_codegen/sync_facade/ --target bus\n\n"
        f"--- stderr ---\n{result.stderr}\n"
        f"--- stdout ---\n{result.stdout}"
    )


def test_generator_check_mode_scheduler_exits_zero() -> None:
    """Generator --target scheduler --check exits 0 when scheduler/sync.py is current."""
    result = run_generator_check("scheduler")
    assert result.returncode == 0, (
        "Generator --target scheduler --check exited non-zero — scheduler/sync.py has drifted.\n"
        "Re-run locally to update it:\n"
        "  uv run python codegen/src/hassette_codegen/sync_facade/ --target scheduler\n\n"
        f"--- stderr ---\n{result.stderr}\n"
        f"--- stdout ---\n{result.stdout}"
    )
