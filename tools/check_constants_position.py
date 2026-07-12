#!/usr/bin/env python3
"""CI guard: flag UPPER_CASE module constants defined after the first class/function.

The house convention is that module-level constants sit at the top of the file,
right after imports, so a reader can see the file's configuration surface before
diving into behavior. But that convention has a legitimate exception: a constant
that *derives* from an earlier class or function necessarily has to come after it —
``DEFAULT_OVERLAP_MODE = ExecutionMode.SINGLE`` cannot appear before ``ExecutionMode``
is defined.

Detection is AST-based and only looks at top-level module statements (``tree.body``).
A constant is a module-level ``ast.Assign``/``ast.AnnAssign`` whose target(s) are all
UPPER_CASE names (2+ characters, not a dunder like ``__all__``). It is flagged when it
appears after the first top-level ``ast.ClassDef``/``ast.FunctionDef``/``ast.AsyncFunctionDef``
in the module, UNLESS it references a name bound by an earlier top-level statement —
a class, a function, or another module-level assignment target — collected by walking
its value (and, for ``ast.AnnAssign``, its annotation too, since annotations are
evaluated at runtime in this codebase) for ``ast.Name`` nodes and matching against
every name bound earlier in the same module body. Checking the annotation as well as
the value matters: a ``ContextVar[SomeClass | None]`` annotation evaluates ``SomeClass``
at import time exactly like a value expression would. Checking earlier assignment
targets (not just classes/functions) matters too, so a constant-derived-from-a-constant
chain is exempted as a whole rather than only its first link. That heuristic auto-exempts
the common "derived constant" shapes:

    class ExecutionMode(Enum):
        SINGLE = "single"

    DEFAULT_OVERLAP_MODE = ExecutionMode.SINGLE  # references ExecutionMode -> exempt

    def sort_harness_graph(deps): ...

    STARTUP_ORDER = sort_harness_graph(DEPENDENCIES)  # references sort_harness_graph -> exempt

    def build_columns(): ...

    _COLUMNS = build_columns()  # references build_columns -> exempt
    _INSERT_SQL = f"INSERT INTO t ({', '.join(_COLUMNS)})"  # references _COLUMNS -> exempt too

    @dataclass
    class Handle:
        thread: threading.Thread | None = None

    HANDLE_VAR: ContextVar[Handle | None] = ContextVar("handle")  # annotation references Handle -> exempt

The ``# constant-after-def:`` annotation is the escape hatch for the rare constant
that legitimately needs to sit after a def but doesn't reference it in a way the AST
can see. It requires a non-empty reason after the colon, matched the same way as
``# lazy-import:`` in check_lazy_imports.py: anywhere on the assignment's own physical
line span, or on the comment-only line immediately preceding it.

Canonical annotation form: ``# constant-after-def: <reason>``

Usage:
    python tools/check_constants_position.py [FILE ...]

With no arguments, scans every file under src/, tests/, scripts/, tools/, codegen/,
docs/, and examples/. Given file paths (as pre-commit passes the staged files), scans
only those — out-of-scope or non-Python paths are ignored.
"""

import ast
import re
import sys
from pathlib import Path

from lint_helpers import DEFAULT_SCAN_DIRS, REPO_ROOT, iter_python_files, run_check

# Matches the annotation followed by a non-empty reason (at least one
# non-whitespace character after the colon).
ANNOTATION_RE = re.compile(r"#\s*constant-after-def:\s*\S")

DUNDER_RE = re.compile(r"^__.+__$")
CONSTANT_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _is_constant_name(name: str) -> bool:
    """Return True if ``name`` reads as an UPPER_CASE constant by house convention."""
    if len(name) < 2:
        return False
    if DUNDER_RE.match(name):
        return False
    return bool(CONSTANT_NAME_RE.match(name))


def _collect_name_targets(target: ast.expr) -> list[str] | None:
    """Return the flat list of names bound by an assignment target, or None if unsupported.

    Handles plain names (``FOO = 1``) and tuple/list unpacking (``FOO, BAR = 1, 2``).
    Any other target shape (attribute, subscript, starred) returns None so the caller
    skips the statement rather than misjudging it.
    """
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            collected = _collect_name_targets(elt)
            if collected is None:
                return None
            names.extend(collected)
        return names
    return None


def _extract_target_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    """Return the names bound by a module-level Assign/AnnAssign, or [] if not applicable."""
    if isinstance(node, ast.AnnAssign):
        if node.value is None or not isinstance(node.target, ast.Name):
            return []
        return [node.target.id]

    names: list[str] = []
    for target in node.targets:
        collected = _collect_name_targets(target)
        if collected is None:
            return []
        names.extend(collected)
    return names


def _references_earlier_binding(
    node: ast.Assign | ast.AnnAssign, bound_names: dict[str, int], current_index: int
) -> bool:
    """Return True if the statement references a name bound by an earlier top-level statement.

    Walks ``node.value`` and, for ``ast.AnnAssign``, ``node.annotation`` too — both are
    evaluated at import time in this codebase (no ``from __future__ import annotations``),
    so a subscripted annotation like ``ContextVar[Handle | None]`` needs ``Handle`` to
    already be bound exactly like a value expression would.
    """
    exprs: list[ast.expr] = [node.value] if node.value is not None else []
    if isinstance(node, ast.AnnAssign):
        exprs.append(node.annotation)

    for expr in exprs:
        for sub in ast.walk(expr):
            if isinstance(sub, ast.Name) and bound_names.get(sub.id, current_index) < current_index:
                return True
    return False


def is_exempt(lines: list[str], lineno: int, end_lineno: int) -> bool:
    """Return True if the assignment spanning [lineno, end_lineno] carries a defend comment.

    Accepts the annotation anywhere on the statement's own physical lines, or on the
    comment-only line immediately preceding it (1-based line numbers).
    """
    for i in range(lineno - 1, end_lineno):
        if ANNOTATION_RE.search(lines[i]):
            return True

    if lineno >= 2:
        prev = lines[lineno - 2].strip()
        if prev.startswith("#") and ANNOTATION_RE.search(prev):
            return True

    return False


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return (1-based line number, statement text) for constants misplaced after a def."""
    source = path.read_text()
    lines = source.splitlines()
    tree = ast.parse(source)

    # Every name bound by a top-level class, function, or assignment, mapped to its body
    # index. Assignment targets are included (not just classes/functions) so a constant
    # that derives from another earlier constant — which itself derives from a function —
    # is recognized as part of the same legitimate dependency chain.
    bound_names: dict[str, int] = {}
    first_def_index: int | None = None
    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            bound_names[node.name] = i
            if first_def_index is None:
                first_def_index = i
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for name in _extract_target_names(node):
                bound_names.setdefault(name, i)

    if first_def_index is None:
        return []

    violations: list[tuple[int, str]] = []
    for i, node in enumerate(tree.body):
        if i <= first_def_index:
            continue
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        names = _extract_target_names(node)
        if not names or not all(_is_constant_name(name) for name in names):
            continue

        if _references_earlier_binding(node, bound_names, i):
            continue

        end_lineno = node.end_lineno or node.lineno
        if is_exempt(lines, node.lineno, end_lineno):
            continue

        violations.append((node.lineno, lines[node.lineno - 1].strip()))

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
        summary="UPPER_CASE constant(s) defined after the first class/function",
        ok=f"no misplaced constants found under {', '.join(DEFAULT_SCAN_DIRS)}/.",
        footer=(
            "Move each flagged constant above the first class/function definition. If it\n"
            "genuinely needs to stay (and doesn't reference an earlier def), annotate the line:\n"
            "'# constant-after-def: <reason>' (the reason is required)."
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
