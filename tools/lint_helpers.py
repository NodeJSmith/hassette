"""Shared helpers for the hand-written lint scripts in this directory.

Kept here rather than copied into each ``check_*.py`` so the AST/path logic has a
single source of truth. These scripts run both as pytest modules (``tools`` is on
the test path) and as standalone executables (``./tools/check_*.py`` puts this
directory on ``sys.path``), so a bare ``from lint_helpers import ...`` resolves in
both contexts.
"""

import ast
from collections.abc import Callable
from pathlib import Path


def run_check(
    paths: list[Path],
    repo_root: Path,
    check: Callable[[Path], list[tuple[int, str]]],
    *,
    summary: str,
    ok: str,
    footer: str | None = None,
) -> int:
    """Run ``check`` over ``paths`` and print the standard violation report.

    Both ``summary`` and ``ok`` are the checker-specific remainder after the standard
    status prefix: ``summary`` is wrapped as ``ERROR: <n> <summary>:`` above the
    violation list, and ``ok`` as ``OK: <ok>`` when nothing is found. ``footer`` is
    optional guidance printed after the list. Returns 1 when any violation is found,
    0 otherwise. Checkers that report a single kind of (line, message) violation share
    this; ``check_spec_tokens`` reports two kinds (content and filename) and keeps its
    own runner.
    """
    violations: list[tuple[Path, int, str]] = []
    for path in paths:
        rel = path.relative_to(repo_root)
        for lineno, message in check(path):
            violations.append((rel, lineno, message))

    if violations:
        print(f"ERROR: {len(violations)} {summary}:")
        print()
        for rel, lineno, message in violations:
            print(f"  {rel}:{lineno} — {message}")
        if footer:
            print()
            print(footer)
        return 1

    print(f"OK: {ok}")
    return 0


def docstring_spans(tree: ast.AST) -> list[tuple[int, int]]:
    """Return (start, end) 1-based line spans of every docstring in the tree."""
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            spans.append((first.value.lineno, first.value.end_lineno or first.value.lineno))
    return spans


def iter_py_files(repo_root: Path, scan_dirs: list[str]) -> list[Path]:
    """Return every .py file under the given repo-relative directories, sorted for stable output."""
    paths: list[Path] = []
    for scan_dir in scan_dirs:
        paths.extend((repo_root / scan_dir).rglob("*.py"))
    return sorted(paths)
