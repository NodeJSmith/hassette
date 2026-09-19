"""Characterization tests for tools/check_file_size_regressions.py.

Pins the "new code" file-size gate: house-lint's own subprocess call is mocked (external tool
boundary), but the git-diff side runs against a real throwaway repo (see the `git_repo` fixture
in conftest.py) so the actual comparison logic -- growth vs. shrink, renames, untouched files --
is exercised for real rather than asserting whatever a mock was told to return.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from check_file_size_regressions import HouseLintError, current_oversized_files, regressions

from .conftest import GitRepo


def _house_lint_result(findings: list[dict]) -> MagicMock:
    payload = {"findings": findings}
    return MagicMock(stdout=json.dumps(payload), returncode=1 if findings else 0)


def test_current_oversized_files_parses_hsl102_findings() -> None:
    findings = [
        {"rule_id": "HSL102", "path": "src/big.py", "message": "900 lines (threshold: 800)"},
        {"rule_id": "HSL900", "path": "src/other.py", "message": "unused suppression"},
    ]
    with patch("check_file_size_regressions.subprocess.run", return_value=_house_lint_result(findings)):
        assert current_oversized_files(Path("/repo")) == {Path("src/big.py"): 900}


def test_current_oversized_files_empty_when_no_findings() -> None:
    with patch("check_file_size_regressions.subprocess.run", return_value=_house_lint_result([])):
        assert current_oversized_files(Path("/repo")) == {}


def test_current_oversized_files_raises_on_unparseable_message() -> None:
    findings = [{"rule_id": "HSL102", "path": "src/big.py", "message": "garbage"}]
    with (
        patch("check_file_size_regressions.subprocess.run", return_value=_house_lint_result(findings)),
        pytest.raises(HouseLintError, match="unrecognized HSL102 message"),
    ):
        current_oversized_files(Path("/repo"))


def test_current_oversized_files_raises_on_invalid_json() -> None:
    with (
        patch("check_file_size_regressions.subprocess.run", return_value=MagicMock(stdout="not json")),
        pytest.raises(HouseLintError, match="did not produce valid JSON"),
    ):
        current_oversized_files(Path("/repo"))


def test_current_oversized_files_raises_when_house_lint_missing() -> None:
    with (
        patch("check_file_size_regressions.subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(HouseLintError, match="not on PATH"),
    ):
        current_oversized_files(Path("/repo"))


def test_current_oversized_files_raises_when_house_lint_reports_scan_errors() -> None:
    # house-lint exits 3 (config/scan errors) or 4 (internal error) when part of the tree
    # couldn't be scanned -- its `findings` list is then partial, not empty, so silently trusting
    # it would let a genuinely oversized file that failed to scan slip past this gate unflagged.
    payload = {
        "findings": [{"rule_id": "HSL102", "path": "src/big.py", "message": "900 lines (threshold: 800)"}],
        "errors": [{"kind": "config", "message": "could not parse src/broken.py"}],
    }
    result = MagicMock(stdout=json.dumps(payload), returncode=3)
    with (
        patch("check_file_size_regressions.subprocess.run", return_value=result),
        pytest.raises(HouseLintError, match="scan errors"),
    ):
        current_oversized_files(Path("/repo"))


def test_regressions_flags_a_file_that_grew_past_the_threshold(git_repo: GitRepo) -> None:
    git_repo.write("src/big.py", "line\n" * 900)
    base = git_repo.commit("base")

    git_repo.write("src/big.py", "line\n" * 950)
    head = git_repo.commit("grow it")

    oversized = {Path("src/big.py"): 950}
    found = regressions(git_repo.root, oversized, base, head)
    assert found == [(Path("src/big.py"), 900, 950)]


def test_regressions_uses_merge_base_not_a_diverged_base_ref_tip(git_repo: GitRepo) -> None:
    # base_ref is the PR's raw base ref, which may have moved past the PR's actual branch point
    # by the time CI runs. regressions() must diff against the merge-base, not base_ref's live
    # tip -- otherwise an unrelated commit on the base branch after the PR forked could make this
    # PR's own untouched growth invisible (or blame it for growth it didn't cause).
    git_repo.write("src/big.py", "line\n" * 900)
    branch_point = git_repo.commit("branch point")

    git_repo.write("src/big.py", "line\n" * 950)
    head = git_repo.commit("PR grows the file")

    # Base branch moves on, unrelated to the PR, shrinking the same file after the branch point.
    diverged_base_tip = git_repo.diverge(
        "src/big.py", "line\n" * 100, "unrelated: base branch shrinks the file", branch_point
    )

    oversized = {Path("src/big.py"): 950}
    # If base_ref's live tip (100 lines) were used directly, this PR's 900->950 growth would
    # register as 100->950 -- still "grew", but for the wrong reason and with a bogus old count.
    found = regressions(git_repo.root, oversized, diverged_base_tip, head)
    assert found == [(Path("src/big.py"), 900, 950)]


def test_regressions_ignores_a_file_that_shrank_but_is_still_oversized(git_repo: GitRepo) -> None:
    git_repo.write("src/big.py", "line\n" * 900)
    base = git_repo.commit("base")

    git_repo.write("src/big.py", "line\n" * 850)
    head = git_repo.commit("shrink it a bit")

    oversized = {Path("src/big.py"): 850}
    assert regressions(git_repo.root, oversized, base, head) == []


def test_regressions_ignores_untouched_oversized_files(git_repo: GitRepo) -> None:
    git_repo.write("src/big.py", "line\n" * 900)
    git_repo.write("src/other.py", "x\n")
    base = git_repo.commit("base")

    git_repo.write("src/other.py", "x\ny\n")
    head = git_repo.commit("touch a different file")

    # src/big.py is oversized but this PR never touched it -- pre-existing debt, not blocked.
    oversized = {Path("src/big.py"): 900}
    assert regressions(git_repo.root, oversized, base, head) == []


def test_regressions_flags_a_brand_new_oversized_file(git_repo: GitRepo) -> None:
    git_repo.write("src/a.py", "x\n")
    base = git_repo.commit("base")

    git_repo.write("src/new_big.py", "line\n" * 850)
    head = git_repo.commit("add a new oversized file")

    oversized = {Path("src/new_big.py"): 850}
    found = regressions(git_repo.root, oversized, base, head)
    assert found == [(Path("src/new_big.py"), 0, 850)]


def test_regressions_resolves_renames_before_comparing(git_repo: GitRepo) -> None:
    git_repo.write("src/old_name.py", "line\n" * 900)
    base = git_repo.commit("base")

    subprocess.run(["git", "rm", "-q", "src/old_name.py"], cwd=git_repo.root, check=True)
    git_repo.write("src/new_name.py", "line\n" * 850)
    head = git_repo.commit("rename and shrink")

    # Renamed AND shrunk -- must not be flagged as "born at 850 lines from nothing".
    oversized = {Path("src/new_name.py"): 850}
    assert regressions(git_repo.root, oversized, base, head) == []
