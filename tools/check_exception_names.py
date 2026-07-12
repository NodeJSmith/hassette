#!/usr/bin/env python3
"""CI guard: enforce 'exc' naming for bound exception variables in scanned source files.

The house rule is that a caught exception is bound to ``exc`` (or a descriptive
name ending in ``_exc``, like ``retry_exc``) — never ``e``, ``ex``, ``err``, or
``error``. A consistent name makes the bound exception grep-able across the
codebase and removes a class of one-letter-variable review nits.

Detection is AST-based. Every ``ast.ExceptHandler`` with a bound name
(``except X as name:``) is checked; ``except X:`` with no binding is never
flagged since there's nothing to name. A bound name is flagged unless it is
exactly ``exc`` or ends with ``_exc``.

There is no exemption annotation mechanism — there's no legitimate reason to
bind an exception to anything else, so unlike ``check_lazy_imports.py`` this
checker has no escape hatch to defend.

Usage:
    python tools/check_exception_names.py [FILE ...]

With no arguments, scans every file under src/, tests/, scripts/, tools/, codegen/,
docs/, and examples/. Given file paths (as pre-commit passes the staged files), scans
only those — out-of-scope or non-Python paths are ignored.
"""

import ast
import sys
from pathlib import Path

from lint_helpers import DEFAULT_SCAN_DIRS, REPO_ROOT, iter_python_files, run_check


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a sorted list of (1-based line number, handler text) for badly-named exception bindings."""
    source = path.read_text()
    lines = source.splitlines()

    violations = [
        (node.lineno, lines[node.lineno - 1].strip())
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ExceptHandler)
        and node.name is not None
        and node.name != "exc"
        and not node.name.endswith("_exc")
    ]
    return sorted(violations)


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
        summary="exception handler(s) bound to a non-'exc' name",
        ok=f"all bound exception handlers use 'exc' or '*_exc' under {', '.join(DEFAULT_SCAN_DIRS)}/.",
        footer="Rename the bound exception to 'exc' (or a descriptive '*_exc' name, e.g. 'retry_exc').",
    )


if __name__ == "__main__":
    sys.exit(main())
