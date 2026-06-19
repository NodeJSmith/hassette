#!/usr/bin/env python3
"""CI guard: detect lazy imports (imports inside function bodies) in scanned source files.

The house rule is that all imports live at the top of the file. Lazy imports
obscure dependencies, break ``patch("module.lib")`` mocking, and hide import
errors until runtime. The only legitimate use is breaking a circular import,
and those sites must say so out loud.

Detection is AST-based. An import is flagged when its nearest enclosing scope
is a function or method — ``ast.Import`` / ``ast.ImportFrom`` reached while
inside an ``ast.FunctionDef`` / ``ast.AsyncFunctionDef``. Module-level imports,
including those inside a module-level ``if TYPE_CHECKING:`` block, are never
flagged because they sit at function depth zero.

The ``# lazy-import:`` annotation is the escape hatch. It requires a non-empty
reason after the colon — the reason is the whole point, so an empty annotation
does not exempt. Comments are discarded by the AST, so the annotation is matched
against the raw source lines spanning the flagged statement. Two placements are
accepted:

    (a) Anywhere on the import statement's own physical line span — the same
        line as the import, or any continuation line of a parenthesized import.
    (b) The comment-only line immediately preceding the import (no blank line
        between) — for long imports that cannot carry a trailing comment.

Canonical annotation form: ``# lazy-import: break circular import with <module>``

Usage:
    python tools/check_lazy_imports.py
"""

import ast
import re
import sys
from pathlib import Path

from lint_helpers import iter_py_files, run_check

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories scanned for lazy imports, relative to the repo root.
SCAN_DIRS: list[str] = ["src", "tests", "scripts", "tools", "codegen", "docs", "examples"]

ANNOTATION = "# lazy-import:"

# Matches the annotation followed by a non-empty reason (at least one
# non-whitespace character after the colon).
ANNOTATION_RE = re.compile(r"#\s*lazy-import:\s*\S")


class LazyImportVisitor(ast.NodeVisitor):
    """Collect (lineno, end_lineno) for every import reached inside a function body."""

    def __init__(self) -> None:
        self.flagged: list[tuple[int, int]] = []
        self.func_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.func_depth += 1
        self.generic_visit(node)
        self.func_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.func_depth += 1
        self.generic_visit(node)
        self.func_depth -= 1

    def visit_Import(self, node: ast.Import) -> None:
        if self.func_depth > 0:
            self.flagged.append((node.lineno, node.end_lineno or node.lineno))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.func_depth > 0:
            self.flagged.append((node.lineno, node.end_lineno or node.lineno))
        self.generic_visit(node)


def is_exempt(lines: list[str], lineno: int, end_lineno: int) -> bool:
    """Return True if the import spanning [lineno, end_lineno] carries a defend comment.

    Accepts the annotation anywhere on the import's own physical lines, or on the
    comment-only line immediately preceding it (1-based line numbers).
    """
    # lineno/end_lineno are 1-based; lines is 0-indexed, hence the -1 / -2 offsets.
    for i in range(lineno - 1, end_lineno):
        if ANNOTATION_RE.search(lines[i]):
            return True

    if lineno >= 2:
        prev = lines[lineno - 2].strip()
        if prev.startswith("#") and ANNOTATION_RE.search(prev):
            return True

    return False


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a sorted list of (1-based line number, import text) for un-exempt lazy imports."""
    source = path.read_text()
    lines = source.splitlines()
    visitor = LazyImportVisitor()
    visitor.visit(ast.parse(source))

    violations = [
        (lineno, lines[lineno - 1].strip())
        for lineno, end_lineno in visitor.flagged
        if not is_exempt(lines, lineno, end_lineno)
    ]
    return sorted(violations)


def iter_paths() -> list[Path]:
    """Return every .py file under the scanned directories, sorted for stable output."""
    return iter_py_files(REPO_ROOT, SCAN_DIRS)


def main() -> int:
    return run_check(
        iter_paths(),
        REPO_ROOT,
        check_file,
        summary="lazy import(s) found inside function bodies",
        ok=f"no un-annotated lazy imports found under {', '.join(SCAN_DIRS)}/.",
        footer=(
            "Move each import to the top of its file. If it genuinely breaks a circular\n"
            "import, annotate the line: '# lazy-import: <reason>' (the reason is required)."
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
