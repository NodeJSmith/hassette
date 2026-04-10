"""Subprocess regression tests for the sync facade generator in --check mode.

These tests invoke the generator as a subprocess and assert exit code 0 — the
same check that CI's ``git diff --exit-code`` step performs, but surfaced as a
local pytest failure. They act as the bridge between the deleted
``test_recording_sync_facade_drift.py`` and the CI gate, so drift is caught on
every local ``pytest`` run without requiring a push.
"""

import subprocess
from pathlib import Path

# Repo root is three parents up from this file:
#   tests/unit/test_recording_sync_facade_generation.py
#   → tests/unit/ → tests/ → <repo-root>
_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_generator_check_mode_exits_zero() -> None:
    """Generator --target recording --check exits 0 when sync_facade.py is current.

    Fails when ``src/hassette/test_utils/sync_facade.py`` has drifted from its
    sources (``recording_api.py``, ``api.py``, or ``tools/generate_sync_facade.py``).
    On failure the captured stderr describes what changed.
    """
    result = subprocess.run(
        ["uv", "run", "tools/generate_sync_facade.py", "--target", "recording", "--check"],
        cwd=_REPO_ROOT,
        capture_output=True,
        timeout=60,
        text=True,
    )
    assert result.returncode == 0, (
        "Generator --target recording --check exited non-zero — sync_facade.py has drifted.\n"
        "Re-run locally to update it:\n"
        "  uv run tools/generate_sync_facade.py --target recording\n\n"
        f"--- stderr ---\n{result.stderr}\n"
        f"--- stdout ---\n{result.stdout}"
    )


def test_generator_check_mode_api_exits_zero() -> None:
    """Generator --target api --check exits 0 when sync.py is current.

    Smoke-tests the existing api-generation path through --check mode.
    Serves as a regression guard on the WP02 robustness fixes to run_ruff().
    """
    result = subprocess.run(
        ["uv", "run", "tools/generate_sync_facade.py", "--target", "api", "--check"],
        cwd=_REPO_ROOT,
        capture_output=True,
        timeout=60,
        text=True,
    )
    assert result.returncode == 0, (
        "Generator --target api --check exited non-zero — sync.py has drifted.\n"
        "Re-run locally to update it:\n"
        "  uv run tools/generate_sync_facade.py --target api\n\n"
        f"--- stderr ---\n{result.stderr}\n"
        f"--- stdout ---\n{result.stdout}"
    )
