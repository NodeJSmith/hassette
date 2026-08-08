"""Shared fixtures for the hand-written lint-script tests."""

import textwrap
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest


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
