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
SUBPROCESS_TIMEOUT_SECONDS = 30
STUB_GH = """#!/usr/bin/env bash
case "$1 $2" in
    "label create")
        exit 0
        ;;
    "issue list")
        if [ -n "${STUB_ISSUE_LIST_FAIL:-}" ]; then
            echo "stub gh: simulated issue list failure" >&2
            exit 1
        fi
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
    fields: dict[str, str]


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


def parse_github_output(text: str) -> dict[str, str]:
    r"""Parse GITHUB_OUTPUT's `key<<DELIM\nvalue\nDELIM\n` heredoc format into a dict.

    drift_check.py writes this form (a random per-field delimiter) rather than plain `key=value`
    lines so a value containing a newline can never terminate its own field early — see
    write_github_output's docstring in tools/release/drift_check.py.
    """
    fields: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        key, sep, delimiter = lines[i].partition("<<")
        if not sep:
            i += 1
            continue
        i += 1
        value_lines: list[str] = []
        while lines[i] != delimiter:
            value_lines.append(lines[i])
            i += 1
        fields[key] = "\n".join(value_lines)
        i += 1
    return fields


def run_drift_check(
    bin_dir: Path, *, existing_issue: str = "", fail_issue_list: bool = False, **extra_args: str
) -> DriftCheckResult:
    output_file = bin_dir.parent / "github_output"
    output_file.write_text("")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["STUB_EXISTING_ISSUE"] = existing_issue
    env["STUB_ISSUE_LIST_FAIL"] = "1" if fail_issue_list else ""
    env["GITHUB_OUTPUT"] = str(output_file)

    args = ["uv", "run", str(SCRIPT)]
    for key, value in extra_args.items():
        args += [f"--{key.replace('_', '-')}", value]

    result = subprocess.run(
        args, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SECONDS, env=env
    )
    return DriftCheckResult(
        returncode=result.returncode, stderr=result.stderr, fields=parse_github_output(output_file.read_text())
    )


@pytest.mark.integration
def test_no_drift_reports_drift_false(stub_gh_path: Path) -> None:
    result = run_drift_check(
        stub_gh_path, current="1.2.3", latest="1.2.3", label="pypi-drift", label_description="desc"
    )

    assert result.returncode == 0, result.stderr
    assert result.fields["drift"] == "false"
    assert result.fields["current"] == "1.2.3"
    assert result.fields["latest"] == "1.2.3"
    assert result.fields["existing-issue"] == ""


@pytest.mark.integration
def test_drift_with_no_existing_issue(stub_gh_path: Path) -> None:
    result = run_drift_check(
        stub_gh_path, current="1.2.3", latest="1.2.4", label="pypi-drift", label_description="desc"
    )

    assert result.returncode == 0, result.stderr
    assert result.fields["drift"] == "true"
    assert result.fields["existing-issue"] == ""


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
    assert result.fields["drift"] == "true"
    assert result.fields["existing-issue"] == "42"


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
    assert result.fields["drift"] == "false"
    assert result.fields["existing-issue"] == "7"


@pytest.mark.integration
def test_embedded_newline_cannot_smuggle_a_second_output_field(stub_gh_path: Path) -> None:
    r"""A value containing a newline must not forge a separate GITHUB_OUTPUT field.

    ``--latest`` is untrusted (it comes from an external registry) — see write_github_output's
    docstring in drift_check.py. If the script wrote plain ``key=value`` lines instead of the
    heredoc-with-random-delimiter form, a value like ``"1.2.3\ninjected=true"`` would terminate
    the ``latest`` field early and inject a bogus ``injected`` field.
    """
    result = run_drift_check(
        stub_gh_path,
        current="1.2.3",
        latest="1.2.3\ninjected=true",
        label="pypi-drift",
        label_description="desc",
    )

    assert result.returncode == 0, result.stderr
    assert result.fields["latest"] == "1.2.3\ninjected=true"
    assert "injected" not in result.fields


@pytest.mark.integration
def test_failed_issue_lookup_fails_loud_instead_of_filing_a_duplicate(stub_gh_path: Path) -> None:
    """A failed `gh issue list` (auth, rate limit, network) must not be swallowed as "no existing
    issue" — that would let a scheduled run file a duplicate tracking issue instead of surfacing
    the real failure. See find_existing_issue's docstring in drift_check.py.
    """
    result = run_drift_check(
        stub_gh_path,
        fail_issue_list=True,
        current="1.2.3",
        latest="1.2.4",
        label="pypi-drift",
        label_description="desc",
    )

    assert result.returncode != 0
    assert "gh issue list failed" in result.stderr
    assert result.fields == {}
