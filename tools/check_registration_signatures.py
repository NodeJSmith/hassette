#!/usr/bin/env python3
"""CI guard: enforce keyword-only, no-default ``name`` on Bus/Scheduler registration methods.

Bus and Scheduler registration methods (``on_state_change``, ``schedule``, ``run_in``,
etc.) require a stable ``name`` for DB-registered listeners and jobs — see
``ListenerNameRequiredError`` / ``SchedulerNameRequiredError``. Both the Pyright contract
and the runtime guard depend on ``name`` staying keyword-only with no default; a future
edit that reintroduces a default or drops the ``*`` would silently reopen the positional-
arg and optional-name regressions those checks were built to close.

Detection is AST-based, mirroring ``check_lazy_imports.py``. For every public method (not
``_``-prefixed) defined directly on a class in the scanned files, a parameter literally
named ``name`` is checked for two invariants:

1. ``name`` is keyword-only (appears in ``ast.arguments.kwonlyargs``, which only happens
   when a bare ``*`` or ``*args`` precedes it in the signature) rather than positional.
2. The keyword-only ``name`` has no default value (its ``kw_defaults`` entry is ``None``).

Methods without a ``name`` parameter at all (``on_error``, ``cancel_job``, ...) are not
flagged — the scan is structural, not name-prefix-based.

Usage:
    python tools/check_registration_signatures.py

No arguments — the scanned files (``src/hassette/bus/bus.py`` and
``src/hassette/scheduler/scheduler.py``) are hardcoded, matching the design's fixed scope.
"""

import ast
import sys
from pathlib import Path

from lint_helpers import REPO_ROOT, run_check

TARGET_FILES = [
    REPO_ROOT / "src" / "hassette" / "bus" / "bus.py",
    REPO_ROOT / "src" / "hassette" / "scheduler" / "scheduler.py",
]


def _check_method(node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str) -> tuple[int, str] | None:
    """Return a (lineno, message) violation for ``node`` if its ``name`` param is misdeclared."""
    args = node.args
    positional_names = {a.arg for a in (*args.posonlyargs, *args.args)}

    if "name" in positional_names:
        return (node.lineno, f"{class_name}.{node.name}: 'name' parameter must be keyword-only (add '*' before it)")

    kwonly_names = [a.arg for a in args.kwonlyargs]
    if "name" not in kwonly_names:
        return None

    default = args.kw_defaults[kwonly_names.index("name")]
    if default is not None:
        return (node.lineno, f"{class_name}.{node.name}: 'name' parameter must not have a default value")

    return None


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a sorted list of (1-based line number, message) violations in ``path``."""
    source = path.read_text()
    tree = ast.parse(source)

    violations: list[tuple[int, str]] = []
    for class_node in ast.walk(tree):
        if not isinstance(class_node, ast.ClassDef):
            continue
        for item in class_node.body:
            if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) or item.name.startswith("_"):
                continue
            violation = _check_method(item, class_node.name)
            if violation is not None:
                violations.append(violation)

    return sorted(violations)


def main() -> int:
    return run_check(
        TARGET_FILES,
        REPO_ROOT,
        check_file,
        summary="registration method(s) with a misdeclared 'name' parameter",
        ok="all Bus/Scheduler registration methods declare 'name' correctly (keyword-only, no default).",
        footer=(
            "A 'name' parameter on a Bus/Scheduler registration method must be keyword-only\n"
            "(after '*') with no default value, matching the required-name API contract."
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
