"""Shared helpers for the hand-written lint scripts in this directory.

Kept here rather than copied into each ``check_*.py`` so the AST/path logic has a
single source of truth. These scripts run both as pytest modules (``tools`` is on
the test path) and as standalone executables (``./tools/check_*.py`` puts this
directory on ``sys.path``), so a bare ``from lint_helpers import ...`` resolves in
both contexts.
"""

import ast
import io
import re
import subprocess
import tokenize
from collections.abc import Callable
from pathlib import Path

#: Repo root, shared so every checker resolves paths against the same anchor rather than
#: each recomputing ``Path(__file__).resolve().parent.parent`` on its own.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Fallback scan roots, relative to the repo root, for checkers that don't set their own
#: ``SCAN_DIRS``. Most house-style checks (lazy imports, spec tokens, LLM cruft) moved to the
#: house-lint package and no longer call this; remaining callers set their own narrower
#: ``SCAN_DIRS`` instead (``check_test_factories.py`` scans ``tests`` only,
#: ``check_module_boundaries.py`` scans ``src/hassette`` only), so this constant currently has
#: no live full-repo-scan caller.
DEFAULT_SCAN_DIRS: list[str] = ["src", "tests", "scripts", "tools", "codegen", "docs", "examples"]

#: Directory components that are never first-party source: virtualenvs (notably the nested
#: ``codegen/.venv``), caches, and build output. Without this filter, rglob over the ``codegen``
#: scan dir pulls in third-party site-packages and reports them as house-style violations — which
#: fails the linters' own characterization tests on any machine that has a local ``codegen/.venv``.
EXCLUDED_PARTS = frozenset({".venv", "site-packages", "__pycache__", ".nox", ".git", "node_modules"})

#: A unified-diff hunk header, e.g. "@@ -a,b +c,d @@" — b/d default to 1 when omitted (git's
#: convention for a single-line hunk). Used by git_changed_line_ranges() below.
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")

#: git's own wording for "the path isn't in that tree" (as opposed to "the ref itself doesn't
#: resolve", e.g. an unfetched commit) — verified directly against git's actual stderr output,
#: not guessed. Both phrasings appear depending on whether the path exists in the working tree.
#: Used by git_file_line_count_at() below.
_GIT_SHOW_MISSING_PATH_MARKERS = ("does not exist in", "exists on disk, but not in")


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
    this.
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


def iter_ts_files(base_dir: Path) -> list[Path]:
    """Return every .ts/.tsx file under base_dir, sorted, excluding generated .d.ts files.

    Only for callers importing this module directly (same directory as a ``tools/check_*.py``
    script, or under pytest via the ``tools``/``tools/frontend`` ``pythonpath`` entries in
    ``pyproject.toml``). The existing ``tools/frontend/check_*.py`` scripts are each their own
    prek entrypoint (``./tools/frontend/check_*.py``, run as a standalone executable — see
    ``prek.toml``), so their own directory, not this one, lands on ``sys.path`` at runtime; a
    bare ``from lint_helpers import ...`` there would raise ``ModuleNotFoundError``. They keep
    their own copy of this pattern until they're restructured to resolve this module too.
    """
    return sorted(
        path
        for pattern in ("*.ts", "*.tsx")
        for path in base_dir.rglob(pattern)
        if not path.name.endswith(".d.ts") and EXCLUDED_PARTS.isdisjoint(path.relative_to(base_dir).parts)
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
    return resolve_paths(argv, REPO_ROOT, scan_dirs if scan_dirs is not None else DEFAULT_SCAN_DIRS)


# Git-diff helpers for "new code" CI gates — checkers that must flag only a violation this PR's
# own commits introduced, not pre-existing debt the PR happens to sit near. Shared here (rather
# than duplicated per checker) because both the file-size and duplicate-code gates need the same
# three primitives: where the PR actually branched off, which lines it added, and what a file
# looked like before it did.


def git_merge_base(repo_root: Path, base_ref: str, head_ref: str) -> str:
    """Return the commit SHA where ``head_ref`` diverged from ``base_ref``.

    This, not ``base_ref``'s current tip, is the correct comparison point for a "did this PR
    make things worse" gate: using the live tip would blame a PR for unrelated commits that
    landed on the base branch after the PR branched, or hide the PR's own regressions behind an
    unrelated improvement on the base branch.
    """
    result = subprocess.run(
        ["git", "merge-base", base_ref, head_ref], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def git_changed_line_ranges(repo_root: Path, base_ref: str, head_ref: str) -> dict[Path, set[int]]:
    """Return ``{repo-relative path: {new-side line numbers added or modified}}`` in the diff.

    ``--find-renames`` matters here: without it, a renamed file with a handful of real edits
    shows as a full delete-and-add pair, and every one of its lines — not just the edited ones —
    would count as "changed", making an untouched block that merely moved files look brand new.
    A pure rename with zero content change produces no hunks at all and so contributes no
    entries, which is the desired outcome (nothing about that file's content is new).

    Deleted files are skipped (there is no new-side content for a gate about newly-introduced
    lines to point at). Uses ``--unified=0`` so hunk ranges cover only actually-changed lines,
    not surrounding context.
    """
    result = subprocess.run(
        ["git", "diff", "--unified=0", "--find-renames", base_ref, head_ref],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    changed: dict[Path, set[int]] = {}
    current_file: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            current_file = None if target == "/dev/null" else Path(target.removeprefix("b/"))
            continue
        match = _HUNK_HEADER_RE.match(line)
        if match and current_file is not None:
            start = int(match.group("start"))
            count = int(match.group("count") or "1")
            if count:
                changed.setdefault(current_file, set()).update(range(start, start + count))
    return changed


def git_renamed_from(repo_root: Path, base_ref: str, head_ref: str) -> dict[Path, Path]:
    """Return ``{new repo-relative path: old repo-relative path}`` for files git detects as renamed."""
    result = subprocess.run(
        ["git", "diff", "--find-renames", "--name-status", base_ref, head_ref],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    renames: dict[Path, Path] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            renames[Path(parts[2])] = Path(parts[1])
    return renames


def git_file_line_count_at(repo_root: Path, ref: str, path: Path) -> int:
    """Return the line count of ``path`` at ``ref``, or 0 if it doesn't exist there.

    0 for a missing file is deliberate, not a fallback default: a file with no prior line count
    to compare against should read as "born at its current size", which is exactly the case a
    new-code size gate needs to catch. That deliberate 0 must not also catch a *different*
    failure, though — an unresolvable `ref` (e.g. a commit `fetch-depth: 0` should have pulled in
    but didn't) would otherwise silently read as "file didn't exist", reporting a pre-existing
    file's entire current size as 100% new growth. So only git's own "path missing from this
    tree" wording maps to 0; anything else re-raises as the same `CalledProcessError` a sibling
    `check=True` call here would have produced.
    """
    result = subprocess.run(["git", "show", f"{ref}:{path.as_posix()}"], cwd=repo_root, capture_output=True, text=True)
    if result.returncode != 0:
        if any(marker in result.stderr for marker in _GIT_SHOW_MISSING_PATH_MARKERS):
            return 0
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    return len(result.stdout.splitlines())
