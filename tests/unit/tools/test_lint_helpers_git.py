"""Characterization tests for the git-diff helpers in lint_helpers.py.

These back the "new code" CI gates (file-size and duplicate-code regressions scoped to what a
PR actually changed) — see check_file_size_regressions.py and check_duplicate_code.py's
--gate-new-code mode. Pins the exact semantics those gates depend on: merge-base (not branch
tip) as the comparison point, rename-awareness, and deleted/missing files reading as absent
rather than erroring.
"""

import subprocess
from pathlib import Path

import pytest
from lint_helpers import git_changed_line_ranges, git_file_line_count_at, git_merge_base, git_renamed_from

from .conftest import GitRepo


def test_merge_base_is_the_common_ancestor_not_base_tip(git_repo: GitRepo) -> None:
    git_repo.write("a.py", "1\n")
    root = git_repo.commit("root")

    git_repo.write("a.py", "1\n2\n")
    branch_point = git_repo.commit("branch point")

    git_repo.write("a.py", "1\n2\n3\n")
    head = git_repo.commit("pr commit")

    # Simulate main moving on, unrelated to the PR, after the branch point.
    subprocess.run(["git", "checkout", "-q", branch_point], cwd=git_repo.root, check=True)
    git_repo.write("b.py", "unrelated\n")
    later_main = git_repo.commit("unrelated main commit")
    subprocess.run(["git", "checkout", "-q", "main"], cwd=git_repo.root, check=True)

    assert git_merge_base(git_repo.root, later_main, head) == branch_point
    assert git_merge_base(git_repo.root, later_main, head) != root


def test_changed_line_ranges_reports_added_lines(git_repo: GitRepo) -> None:
    git_repo.write("a.py", "one\ntwo\nthree\n")
    base = git_repo.commit("base")

    git_repo.write("a.py", "one\ntwo\nthree\nfour\nfive\n")
    head = git_repo.commit("add lines")

    changed = git_changed_line_ranges(git_repo.root, base, head)
    assert changed == {Path("a.py"): {4, 5}}


def test_changed_line_ranges_excludes_untouched_files(git_repo: GitRepo) -> None:
    git_repo.write("a.py", "one\n")
    git_repo.write("b.py", "untouched\n")
    base = git_repo.commit("base")

    git_repo.write("a.py", "one\ntwo\n")
    head = git_repo.commit("touch only a.py")

    changed = git_changed_line_ranges(git_repo.root, base, head)
    assert Path("b.py") not in changed


def test_changed_line_ranges_pure_deletion_reports_no_added_lines(git_repo: GitRepo) -> None:
    git_repo.write("a.py", "one\ntwo\nthree\n")
    base = git_repo.commit("base")

    git_repo.write("a.py", "one\nthree\n")
    head = git_repo.commit("delete a line")

    # A pure removal has no "+" side to report — nothing new was introduced.
    assert git_changed_line_ranges(git_repo.root, base, head) == {}


def test_changed_line_ranges_pure_rename_reports_no_added_lines(git_repo: GitRepo) -> None:
    git_repo.write("old_name.py", "same content\n" * 10)
    base = git_repo.commit("base")

    git_repo.rm("old_name.py")
    git_repo.write("new_name.py", "same content\n" * 10)
    head = git_repo.commit("pure rename")

    # No content changed, so no lines should read as "new" under the new path.
    assert git_changed_line_ranges(git_repo.root, base, head) == {}


def test_changed_line_ranges_rename_with_edits_only_counts_the_edited_lines(git_repo: GitRepo) -> None:
    original = "".join(f"line {i}\n" for i in range(10))
    git_repo.write("old_name.py", original)
    base = git_repo.commit("base")

    git_repo.rm("old_name.py")
    edited = original.replace("line 5\n", "line 5 edited\n")
    git_repo.write("new_name.py", edited)
    head = git_repo.commit("rename with one edit")

    changed = git_changed_line_ranges(git_repo.root, base, head)
    # Only the single edited line counts as new — not the whole 10-line file, which a
    # naive delete-and-add (no rename detection) would report.
    assert changed == {Path("new_name.py"): {6}}


def test_renamed_from_maps_new_path_to_old_path(git_repo: GitRepo) -> None:
    git_repo.write("old_name.py", "content\n" * 10)
    base = git_repo.commit("base")

    git_repo.rm("old_name.py")
    git_repo.write("new_name.py", ("content\n" * 10) + "one more line\n")
    head = git_repo.commit("rename with edit")

    assert git_renamed_from(git_repo.root, base, head) == {Path("new_name.py"): Path("old_name.py")}


def test_renamed_from_empty_when_nothing_renamed(git_repo: GitRepo) -> None:
    git_repo.write("a.py", "one\n")
    base = git_repo.commit("base")

    git_repo.write("a.py", "one\ntwo\n")
    head = git_repo.commit("edit in place")

    assert git_renamed_from(git_repo.root, base, head) == {}


def test_file_line_count_at_existing_file(git_repo: GitRepo) -> None:
    git_repo.write("a.py", "one\ntwo\nthree\n")
    ref = git_repo.commit("base")

    assert git_file_line_count_at(git_repo.root, ref, Path("a.py")) == 3


def test_file_line_count_at_missing_file_returns_zero(git_repo: GitRepo) -> None:
    git_repo.write("a.py", "one\n")
    ref = git_repo.commit("base")

    assert git_file_line_count_at(git_repo.root, ref, Path("does_not_exist.py")) == 0


def test_file_line_count_at_unresolvable_ref_raises_rather_than_returning_zero(git_repo: GitRepo) -> None:
    # An unresolvable ref (e.g. a commit fetch-depth:0 should have pulled in but didn't) is a
    # different failure than "the file wasn't there yet" and must not be silently treated as one
    # -- that would misreport a pre-existing file's whole current size as new growth.
    git_repo.write("a.py", "one\n")

    with pytest.raises(subprocess.CalledProcessError):
        git_file_line_count_at(git_repo.root, "not-a-real-ref", Path("a.py"))
