"""Tests for the shared lint-script helpers, focused on ``resolve_paths``.

``resolve_paths`` is what lets the checkers run as pre-commit hooks: pre-commit
passes the staged files as arguments, so a checker scans only what changed instead
of re-walking the whole tree. With no arguments it falls back to a full scan — the
behaviour CI (``prek run --all-files``) and a manual full sweep rely on.
"""

from pathlib import Path

import pytest
from lint_helpers import resolve_paths


def _make_repo(root: Path) -> None:
    """Lay down a small repo: src/a.py, tests/b.py, an out-of-scope file, and a .venv file."""
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "other").mkdir()
    (root / "src" / ".venv").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n")
    (root / "tests" / "b.py").write_text("y = 2\n")
    (root / "other" / "c.py").write_text("z = 3\n")
    (root / "src" / ".venv" / "vendored.py").write_text("w = 4\n")


def test_no_args_scans_the_full_tree(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    # No argv → full scan: every in-scope .py, with the out-of-scope and .venv files dropped.
    expected = [tmp_path / "src" / "a.py", tmp_path / "tests" / "b.py"]
    assert resolve_paths([], tmp_path, ["src", "tests"]) == expected


def test_single_in_scope_file_returns_only_that_file(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    target = tmp_path / "src" / "a.py"
    assert resolve_paths([str(target)], tmp_path, ["src", "tests"]) == [target]


def test_relative_arg_resolves_against_repo_root(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    assert resolve_paths(["src/a.py"], tmp_path, ["src", "tests"]) == [tmp_path / "src" / "a.py"]


def test_out_of_scope_file_is_ignored(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    # other/c.py is a real .py file but lives outside the scan dirs — dropped, not crashed.
    assert resolve_paths([str(tmp_path / "other" / "c.py")], tmp_path, ["src", "tests"]) == []


def test_excluded_venv_file_is_ignored(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    # Under a scan dir, but inside a .venv — EXCLUDED_PARTS keeps vendored code out.
    assert resolve_paths([str(tmp_path / "src" / ".venv" / "vendored.py")], tmp_path, ["src"]) == []


@pytest.mark.parametrize(
    "rel_arg",
    ["src/readme.md", "src/missing.py", "src"],
    ids=["wrong-suffix", "missing-file", "directory"],
)
def test_non_qualifying_arg_is_ignored(tmp_path: Path, rel_arg: str) -> None:
    _make_repo(tmp_path)
    (tmp_path / "src" / "readme.md").write_text("# not python\n")  # wrong suffix, exists
    # Each case is a distinct reason to skip: wrong suffix, missing file, or a directory.
    assert resolve_paths([str(tmp_path / rel_arg)], tmp_path, ["src"]) == []


def test_result_is_sorted_and_deduplicated(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    src_py = tmp_path / "src" / "a.py"
    tests_py = tmp_path / "tests" / "b.py"
    # Pass tests_py before src_py, and src_py twice — output is sorted and carries no duplicate.
    assert resolve_paths([str(tests_py), str(src_py), "src/a.py"], tmp_path, ["src", "tests"]) == [src_py, tests_py]
