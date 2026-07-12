#!/usr/bin/env python3
"""CI guard: flag ``if TYPE_CHECKING:`` blocks sandwiched between import groups.

The house rule is that an ``if TYPE_CHECKING:`` block sits at the end of the
import section — after every regular ``import``/``from ... import`` statement,
not in the middle of them. A block sandwiched between two groups of regular
imports makes the import order confusing to scan, and it risks runtime vs.
type-time confusion: a reader skimming top-to-bottom may assume everything
above the block is unconditionally imported, then miss that a later import
was actually meant to sit alongside the ``TYPE_CHECKING`` names.

Detection is AST-based and only looks at top-level module statements
(``tree.body``) — nested ``TYPE_CHECKING`` blocks (inside a class or function)
are out of scope, since this rule is about the module's import section. A
top-level ``ast.If`` node is treated as a ``TYPE_CHECKING`` guard when its test
is either the bare name ``TYPE_CHECKING`` or the attribute
``typing.TYPE_CHECKING``. The guard is flagged when any ``ast.Import`` or
``ast.ImportFrom`` statement appears later in the module body.

Usage:
    python tools/check_type_checking_position.py [FILE ...]

With no arguments, scans every file under src/, tests/, scripts/, tools/, codegen/,
docs/, and examples/. Given file paths (as pre-commit passes the staged files), scans
only those — out-of-scope or non-Python paths are ignored.
"""

import ast
import sys
from pathlib import Path

from lint_helpers import DEFAULT_SCAN_DIRS, REPO_ROOT, iter_python_files, run_check


def is_type_checking_guard(test: ast.expr) -> bool:
    """Return True if ``test`` is ``TYPE_CHECKING`` or ``typing.TYPE_CHECKING``."""
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if not (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"):
        return False
    return isinstance(test.value, ast.Name) and test.value.id == "typing"


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return (1-based line number, message) for each mispositioned TYPE_CHECKING block."""
    source = path.read_text()
    tree = ast.parse(source)

    violations: list[tuple[int, str]] = []
    for i, node in enumerate(tree.body):
        if not (isinstance(node, ast.If) and is_type_checking_guard(node.test)):
            continue

        later_import = next(
            (later for later in tree.body[i + 1 :] if isinstance(later, (ast.Import, ast.ImportFrom))),
            None,
        )
        if later_import is not None:
            message = f"if TYPE_CHECKING: block at line {node.lineno} followed by imports at line {later_import.lineno}"
            violations.append((node.lineno, message))

    return violations


def iter_paths() -> list[Path]:
    """Return every .py file under the scanned directories, sorted for stable output.

    The full-scan entry point the characterization tests parametrize over; ``main`` calls
    ``iter_python_files`` directly so a pre-commit run can scan just the staged files. Both go
    through ``iter_python_files``, so the full-scan path can't drift from the per-file path.
    """
    return iter_python_files([])


def main() -> int:
    return run_check(
        iter_python_files(sys.argv[1:]),
        REPO_ROOT,
        check_file,
        summary="if TYPE_CHECKING: block(s) sandwiched between import groups",
        ok=f"no mispositioned TYPE_CHECKING blocks found under {', '.join(DEFAULT_SCAN_DIRS)}/.",
        footer="Move each flagged 'if TYPE_CHECKING:' block to after the last regular import statement.",
    )


if __name__ == "__main__":
    sys.exit(main())
