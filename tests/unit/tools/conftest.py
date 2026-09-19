"""Shared fixtures for the hand-written lint-script tests."""

import subprocess
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest


@dataclass
class GitRepo:
    """A throwaway git repo under ``tmp_path``, for tests of the git-diff lint helpers."""

    root: Path

    def write(self, rel_path: str, content: str) -> None:
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def rm(self, rel_path: str) -> None:
        (self.root / rel_path).unlink()

    def commit(self, message: str) -> str:
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=self.root, check=True, capture_output=True)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, check=True, capture_output=True, text=True
        ).stdout.strip()

    def diverge(self, rel_path: str, content: str, message: str, from_ref: str, back_to: str = "main") -> str:
        """Check out `from_ref`, commit an unrelated change, then return to `back_to`.

        Simulates the base branch moving on, unrelated to the PR, after the PR's branch point --
        the shared setup behind every test proving the "new code" gates diff against merge-base,
        not `base_ref`'s live tip.
        """
        subprocess.run(["git", "checkout", "-q", from_ref], cwd=self.root, check=True)
        self.write(rel_path, content)
        diverged_tip = self.commit(message)
        subprocess.run(["git", "checkout", "-q", back_to], cwd=self.root, check=True)
        return diverged_tip


@pytest.fixture
def git_repo(tmp_path: Path) -> GitRepo:
    """An isolated git repo with a configured committer identity, ready for real commits.

    Real git plumbing rather than mocked subprocess output: the git-diff helpers are thin
    wrappers over `git diff`/`git show`/`git merge-base`, and their exact output format (hunk
    headers, rename markers, `+++`/`---` lines) is the thing under test — mocking it would just
    re-assert whatever the mock was told to return.
    """
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    return GitRepo(tmp_path)


@pytest.fixture
def write_sample(tmp_path: Path) -> Callable[[str], Path]:
    """Return a helper that writes dedented content to a sample .py file and returns its path."""

    def _write(content: str) -> Path:
        target = tmp_path / "sample.py"
        target.write_text(textwrap.dedent(content))
        return target

    return _write


def make_frontend_src(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> Path:
    """Point `module`'s REPO_ROOT/FRONTEND_SRC constants at an isolated tmp_path frontend tree.

    Shared by the tools/frontend/check_*.py test files' own `frontend_env` fixtures, which each
    extend this for whatever additional path constants (GLOBAL_CSS, MEDIA_QUERY_TS, EXEMPTIONS,
    ...) their own module reads, and create any subdirectories their own tests need.

    Args:
        tmp_path: Pytest's per-test temp directory, used as the isolated repo root.
        monkeypatch: Used to patch `module`'s path constants for the duration of the test.
        module: The `tools/frontend/check_*.py` module under test, whose `REPO_ROOT` and
            `FRONTEND_SRC` constants get pointed at the isolated tree.

    Returns:
        The isolated `frontend/src` path, so callers can populate it with test fixtures.
    """
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "FRONTEND_SRC", src)
    return src
