"""Shared helpers for the hand-written lint scripts in this directory.

Kept here rather than copied into each ``check_*.py`` so the AST/path logic has a
single source of truth. These scripts run both as pytest modules (``tools`` is on
the test path) and as standalone executables (``./tools/check_*.py`` puts this
directory on ``sys.path``), so a bare ``from lint_helpers import ...`` resolves in
both contexts.
"""

import ast
from pathlib import Path


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
