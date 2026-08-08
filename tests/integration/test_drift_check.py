"""Verify tools/release/drift_check.py — the shared compare/dedup logic used by
pypi-drift-check.yml, docker-drift-check.yml, and ha-version-drift.yml.

Runs the script as a subprocess (it's a standalone `uv run --script`, not an importable module —
see tools/release/check_wheel_spa.py and test_packaging.py for the established pattern) against
a stub `gh` binary placed first on PATH, so no real GitHub API calls happen.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "tools" / "release" / "drift_check.py"
STUB_GH = """#!/usr/bin/env bash
case "$1 $2" in
    "label create")
        exit 0
        ;;
    "issue list")
        echo "${STUB_EXISTING_ISSUE:-}"
        exit 0
        ;;
    *)
        echo "stub gh: unhandled args: $*" >&2
        exit 1
        ;;
esac
"""


@dataclass(frozen=True)
class DriftCheckResult:
    returncode: int
    stderr: str
    github_output: str


@pytest.fixture
def stub_gh_path(tmp_path: Path) -> Path:
    """Put a fake `gh` binary first on PATH so the script's `gh label create` /
    `gh issue list` calls resolve to a controllable stub instead of the real CLI.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(STUB_GH)
    gh.chmod(0o755)
    return bin_dir


def run_drift_check(bin_dir: Path, *, existing_issue: str = "", **extra_args: str) -> DriftCheckResult:
    output_file = bin_dir.parent / "github_output"
    output_file.write_text("")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["STUB_EXISTING_ISSUE"] = existing_issue
    env["GITHUB_OUTPUT"] = str(output_file)

    args = ["uv", "run", str(SCRIPT)]
    for key, value in extra_args.items():
        args += [f"--{key.replace('_', '-')}", value]

    result = subprocess.run(args, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30, env=env)
    return DriftCheckResult(returncode=result.returncode, stderr=result.stderr, github_output=output_file.read_text())


@pytest.mark.integration
def test_no_drift_reports_drift_false(stub_gh_path: Path) -> None:
    result = run_drift_check(
        stub_gh_path, current="1.2.3", latest="1.2.3", label="pypi-drift", label_description="desc"
    )

    assert result.returncode == 0, result.stderr
    assert "drift=false" in result.github_output
    assert "current=1.2.3" in result.github_output
    assert "latest=1.2.3" in result.github_output
    assert "existing-issue=" in result.github_output


@pytest.mark.integration
def test_drift_with_no_existing_issue(stub_gh_path: Path) -> None:
    result = run_drift_check(
        stub_gh_path, current="1.2.3", latest="1.2.4", label="pypi-drift", label_description="desc"
    )

    assert result.returncode == 0, result.stderr
    assert "drift=true" in result.github_output
    assert "existing-issue=\n" in result.github_output


@pytest.mark.integration
def test_drift_with_existing_issue_is_deduped(stub_gh_path: Path) -> None:
    result = run_drift_check(
        stub_gh_path,
        existing_issue="42",
        current="1.2.3",
        latest="1.2.4",
        label="pypi-drift",
        label_description="desc",
    )

    assert result.returncode == 0, result.stderr
    assert "drift=true" in result.github_output
    assert "existing-issue=42" in result.github_output


@pytest.mark.integration
def test_no_drift_still_reports_existing_issue_for_resync_close(stub_gh_path: Path) -> None:
    """ha-version-drift.yml's auto-close-on-resync step relies on existing-issue being
    populated even when there's no drift, so it doesn't need its own separate dedup lookup.
    """
    result = run_drift_check(
        stub_gh_path,
        existing_issue="7",
        current="2024.1.0",
        latest="2024.1.0",
        label="ha-version-drift",
        label_description="desc",
    )

    assert result.returncode == 0, result.stderr
    assert "drift=false" in result.github_output
    assert "existing-issue=7" in result.github_output
