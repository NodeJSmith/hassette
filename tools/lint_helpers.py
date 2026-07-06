"""Shared helpers for the hand-written lint scripts in this directory.

Kept here rather than copied into each ``check_*.py`` so the AST/path logic has a
single source of truth. These scripts run both as pytest modules (``tools`` is on
the test path) and as standalone executables (``./tools/check_*.py`` puts this
directory on ``sys.path``), so a bare ``from lint_helpers import ...`` resolves in
both contexts.
"""

import ast
import io
import tokenize
from collections.abc import Callable
from pathlib import Path

#: Repo root, shared so every checker resolves paths against the same anchor rather than
#: each recomputing ``Path(__file__).resolve().parent.parent`` on its own.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Directories scanned by the general-purpose checkers (lazy imports, spec tokens, LLM cruft),
#: relative to the repo root. ``check_module_boundaries`` scans ``src/hassette`` only and keeps
#: its own scan dirs since that scope is narrower than this default.
DEFAULT_SCAN_DIRS: list[str] = ["src", "tests", "scripts", "tools", "codegen", "docs", "examples"]

#: Directory components that are never first-party source: virtualenvs (notably the nested
#: ``codegen/.venv``), caches, and build output. Without this filter, rglob over the ``codegen``
#: scan dir pulls in third-party site-packages and reports them as house-style violations — which
#: fails the linters' own characterization tests on any machine that has a local ``codegen/.venv``.
EXCLUDED_PARTS = frozenset({".venv", "site-packages", "__pycache__", ".nox", ".git", "node_modules"})


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


def extract_comments(source: str) -> dict[int, str]:
    """Return {1-based line number: comment text} for every COMMENT token in source."""
    comments: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                comments[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError):
        pass
    return comments


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
    """Return every first-party .py file under the given repo-relative directories, sorted.

    Skips the dirs in EXCLUDED_PARTS so the linters never scan installed third-party packages —
    notably the nested ``codegen/.venv``.
    """
    # relative_to(repo_root) scopes the check to repo-internal components, so an ancestor directory
    # sharing an excluded name (e.g. a checkout under /opt/node_modules/) can't blank the scan.
    return sorted(
        path
        for scan_dir in scan_dirs
        for path in (repo_root / scan_dir).rglob("*.py")
        if EXCLUDED_PARTS.isdisjoint(path.relative_to(repo_root).parts)
    )


def resolve_paths(argv: list[str], repo_root: Path, scan_dirs: list[str]) -> list[Path]:
    """Resolve CLI file arguments to first-party .py paths, or scan ``scan_dirs`` when none given.

    Pre-commit passes the staged files as arguments, so the hook checks only what changed
    instead of re-scanning the whole tree on every commit. Running with no arguments falls
    back to a full scan of ``scan_dirs`` — the behaviour CI and a manual full sweep rely on.

    Arguments are kept only when they are existing ``.py`` files under one of ``scan_dirs``
    and clear of EXCLUDED_PARTS, so a stray non-source path is ignored rather than crashing
    a checker that assumes its inputs live in scope.
    """
    if not argv:
        return iter_py_files(repo_root, scan_dirs)

    scan_roots = [(repo_root / scan_dir).resolve() for scan_dir in scan_dirs]
    selected: set[Path] = set()
    for arg in argv:
        path = Path(arg)
        if not path.is_absolute():
            path = repo_root / path
        path = path.resolve()
        if path.suffix != ".py" or not path.is_file():
            continue
        if not any(root in path.parents for root in scan_roots):
            continue
        if not EXCLUDED_PARTS.isdisjoint(path.relative_to(repo_root).parts):
            continue
        selected.add(path)
    return sorted(selected)


def iter_python_files(argv: list[str], scan_dirs: list[str] | None = None) -> list[Path]:
    """Resolve a checker's CLI file arguments against ``REPO_ROOT``, or scan ``scan_dirs``.

    Thin wrapper over ``resolve_paths`` for the common case: every checker anchors at this
    file's parent directory (``REPO_ROOT``) and scans ``DEFAULT_SCAN_DIRS`` unless it needs
    a narrower scope (``check_module_boundaries`` passes its own ``src/hassette``-only list).
    ``argv`` is normally ``sys.argv[1:]`` for a ``main()`` call, or ``[]`` for a full scan.
    """
    return resolve_paths(argv, REPO_ROOT, scan_dirs or DEFAULT_SCAN_DIRS)
