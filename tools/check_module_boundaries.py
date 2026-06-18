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
those rules can pass (tracked in #1079). ``RULES`` is a list so each boundary is
added as it becomes clean.

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

from lint_helpers import iter_py_files, run_check

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


def package_of(path: Path) -> str:
    """Return the dotted package a file's relative imports resolve against.

    ``src/hassette/app/utils.py`` and ``src/hassette/app/__init__.py`` both anchor
    at ``hassette.app`` — the package is every path part except the file stem.
    """
    rel = path.relative_to(SRC.parent).with_suffix("")  # e.g. hassette/app/utils
    return ".".join(rel.parts[:-1])


def type_checking_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Return line spans of the statements inside ``if TYPE_CHECKING:`` blocks.

    Imports within these spans are exempt. Only the ``if`` body is collected — an
    ``else`` branch runs at runtime, so spanning the whole ``if`` node (which would
    cover the ``else``) would wrongly exempt runtime imports there.
    """
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_tc = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )
        if is_tc:
            ranges.extend((stmt.lineno, stmt.end_lineno or stmt.lineno) for stmt in node.body)
    return ranges


def resolved_from_module(node: ast.ImportFrom, package: str | None) -> str | None:
    """Resolve the ``from`` target of an ``ImportFrom`` to an absolute dotted module.

    Absolute imports return ``node.module`` unchanged. Relative imports are resolved
    against ``package`` (``from ..test_utils import x`` inside ``hassette.core`` →
    ``hassette.test_utils``). Returns None when there is no package to anchor a
    relative import or the level climbs above the root.
    """
    if node.level == 0:
        return node.module
    if package is None:
        return None
    base = package.split(".")
    drop = node.level - 1
    if drop >= len(base):
        return None  # climbs to or above the root package — Python rejects this too
    anchor = base[: len(base) - drop] if drop else base
    return ".".join([*anchor, *(node.module.split(".") if node.module else [])])


def runtime_imports(tree: ast.AST, package: str | None = None) -> list[tuple[int, str]]:
    """Return (lineno, imported hassette.* module) for every runtime import.

    ``package`` is the importing module's dotted package, used to resolve relative
    imports; when omitted, relative imports are skipped.
    """
    tc_ranges = type_checking_ranges(tree)

    def in_type_checking(lineno: int) -> bool:
        return any(start <= lineno <= end for start, end in tc_ranges)

    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not in_type_checking(node.lineno):
            module = resolved_from_module(node, package)
            if module == "hassette":
                # Bare ``hassette`` target (``from hassette import test_utils`` or the
                # relative ``from .. import test_utils``): the alias names are the
                # submodules, so reassemble ``hassette.<name>`` per alias.
                out.extend((node.lineno, f"hassette.{alias.name}") for alias in node.names if alias.name != "*")
            elif module and module.startswith("hassette."):
                out.append((node.lineno, module))
        elif isinstance(node, ast.Import) and not in_type_checking(node.lineno):
            out.extend((node.lineno, alias.name) for alias in node.names if alias.name.startswith("hassette."))
    return out


def check_source(source: str, layer: str, package: str | None = None) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) for boundary violations in a source string.

    ``package`` anchors relative imports; pass it to check the relative-import forms.
    """
    tree = ast.parse(source)
    violations = [
        (lineno, f"{rule.name}: imports {module} — {rule.reason}")
        for lineno, module in runtime_imports(tree, package)
        for rule in RULES
        if rule.applies(layer) and rule.forbids(module)
    ]
    return sorted(violations)


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) for every boundary violation in the file."""
    return check_source(path.read_text(), layer_of(path), package_of(path))


def iter_paths() -> list[Path]:
    """Return every .py file under src/hassette, sorted for stable output."""
    return iter_py_files(REPO_ROOT, ["src/hassette"])


def main() -> int:
    return run_check(
        iter_paths(),
        REPO_ROOT,
        check_file,
        summary="module-boundary violation(s)",
        ok=f"no module-boundary violations across {len(RULES)} rule(s).",
    )


if __name__ == "__main__":
    sys.exit(main())
