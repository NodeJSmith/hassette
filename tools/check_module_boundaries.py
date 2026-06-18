#!/usr/bin/env python3
"""CI guard: enforce architectural import boundaries between hassette subpackages.

Hassette has layered subpackages (``types``, ``models``, ``config``, ``api``,
``bus``, ``core``, ``app``, ``web``, ``test_utils``, …). Nothing in the type
checker or test suite stops a lower layer from importing a higher one, so
boundary erosion compiles and passes silently. This guard fails such imports.

Detection is AST-based and considers runtime imports only — anything inside an
``if TYPE_CHECKING:`` block is exempt, since type-only imports do not create a
runtime dependency.

Scope today is the one boundary that is provably clean and highest-value: the
``test_utils`` package holds test helpers and must never be imported by
production code. The full layer DAG and cycle-freedom from the architecture
issue are NOT enforced here — the codebase currently has cross-layer cycles
(``core``↔``bus``, ``conversion``↔``models``, …) that must be refactored before
those rules can pass. ``RULES`` is a list so each boundary is added as it becomes
clean.

These are structural violations, not style — there is no escape hatch. A
production module that needs a test helper signals a misplaced helper, not a
boundary to annotate.

Usage:
    python tools/check_module_boundaries.py
"""

import ast
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lint_helpers import iter_py_files

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "hassette"


@dataclass(frozen=True)
class Rule:
    """A forbidden-import boundary.

    ``applies`` decides whether the rule governs a source file's layer; ``forbids``
    decides whether an imported ``hassette.*`` module name violates it.
    """

    name: str
    applies: Callable[[str], bool]
    forbids: Callable[[str], bool]
    reason: str


RULES: list[Rule] = [
    Rule(
        name="test_utils-isolation",
        applies=lambda layer: layer != "test_utils",
        forbids=lambda module: module == "hassette.test_utils" or module.startswith("hassette.test_utils."),
        reason="production code must not import test helpers from hassette.test_utils",
    ),
]


def layer_of(path: Path) -> str:
    """Return the top-level subpackage name a source file belongs to."""
    rel = path.relative_to(SRC)
    return rel.parts[0] if len(rel.parts) > 1 else "<root>"


def type_checking_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Return line spans of ``if TYPE_CHECKING:`` blocks (their imports are exempt)."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_tc = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )
        if is_tc:
            ranges.append((node.lineno, node.end_lineno or node.lineno))
    return ranges


def runtime_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, imported hassette.* module) for every runtime import."""
    tc = type_checking_ranges(tree)

    def in_tc(lineno: int) -> bool:
        return any(start <= lineno <= end for start, end in tc)

    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("hassette"):
            if not in_tc(node.lineno):
                out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import) and not in_tc(node.lineno):
            out.extend((node.lineno, alias.name) for alias in node.names if alias.name.startswith("hassette."))
    return out


def check_source(source: str, layer: str) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) for boundary violations in a source string."""
    tree = ast.parse(source)
    violations = [
        (lineno, f"{rule.name}: imports {module} — {rule.reason}")
        for lineno, module in runtime_imports(tree)
        for rule in RULES
        if rule.applies(layer) and rule.forbids(module)
    ]
    return sorted(violations)


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) for every boundary violation in the file."""
    return check_source(path.read_text(), layer_of(path))


def iter_paths() -> list[Path]:
    """Return every .py file under src/hassette, sorted for stable output."""
    return iter_py_files(REPO_ROOT, ["src/hassette"])


def main() -> int:
    all_violations: list[tuple[Path, int, str]] = []
    for path in iter_paths():
        rel = path.relative_to(REPO_ROOT)
        for lineno, message in check_file(path):
            all_violations.append((rel, lineno, message))

    if all_violations:
        print(f"ERROR: {len(all_violations)} module-boundary violation(s):")
        print()
        for rel, lineno, message in all_violations:
            print(f"  {rel}:{lineno} — {message}")
        return 1

    print(f"OK: no module-boundary violations across {len(RULES)} rule(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
