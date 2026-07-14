#!/usr/bin/env python3
"""Lint guard: detect un-annotated coordinator-internal accesses in integration tests.

Uses AST + tokenize-comment pattern to detect when integration tests access private attributes
on ``hassette_instance`` (or aliases like ``sm = hassette_instance.session_manager``). Each
site must carry a ``# coordinator-internal`` annotation marking it as a deliberate, reviewed
exception rather than undetected drift toward coupling on framework internals.

Scope: all ``*.py`` files under ``tests/``, excluding ``conftest.py`` files
(test infrastructure that owns teardown, not tests asserting behavior).

Detection is AST-based:

    1. Collect receiver names in scope for a module: the fixture name ``hassette_instance``,
       plus any local variable assigned directly from ``hassette_instance.session_manager``
       (e.g. ``sm = hassette_instance.session_manager``). The alias scan is whole-module, not
       per-function — acceptable here because ``sm`` is used exclusively as a
       ``session_manager`` alias across both files where it appears.
    2. Walk every ``ast.Attribute`` node in the module (regardless of Load/Store context, and
       including expressions nested inside f-strings — CPython parses those as real
       ``FormattedValue`` nodes, not string content). Flag any node whose ``attr`` starts with
       ``_`` and whose ``value`` is a bare ``ast.Name`` in the receiver set.
    3. Because detection is AST-based, an assertion message containing literal text like
       ``"hassette_instance._loop is not set"`` is never flagged — a string literal produces
       no ``ast.Attribute`` node.

Annotations are matched via ``tokenize``-derived comment tokens (``lint_helpers.extract_comments``),
avoiding false positives from annotation-shaped text inside string literals. Two placements are
accepted:

    (a) A comment on the flagged attribute's own physical line.
    (b) A comment-only line immediately preceding the flagged statement (no blank line
        between) — used when the trailing-comment placement would blow the 120-char line
        limit.

Usage:
    python tools/check_coordinator_internal.py
"""

import ast
import sys
from pathlib import Path

from lint_helpers import REPO_ROOT, extract_comments, run_check

TESTS_DIR = REPO_ROOT / "tests"

BASE_RECEIVER = "hassette_instance"

ANNOTATION = "# coordinator-internal"


def discover_files() -> list[Path]:
    return sorted(p for p in TESTS_DIR.rglob("*.py") if p.name != "conftest.py")


class AliasCollector(ast.NodeVisitor):
    """Collect local names assigned directly from ``hassette_instance.session_manager``.

    Whole-module scan rather than per-function scoping — the two files that alias
    ``session_manager`` (``sm = hassette_instance.session_manager``) use the name exclusively
    for that purpose, so a module-wide alias set doesn't produce false positives here.
    """

    def __init__(self) -> None:
        self.receivers: set[str] = {BASE_RECEIVER}

    def visit_Assign(self, node: ast.Assign) -> None:
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and value.attr == "session_manager"
            and isinstance(value.value, ast.Name)
            and value.value.id == BASE_RECEIVER
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.receivers.add(target.id)
        self.generic_visit(node)


class PrivateAccessVisitor(ast.NodeVisitor):
    """Collect (lineno, end_lineno, attr) for every private-attribute access on a known receiver."""

    def __init__(self, receivers: set[str]) -> None:
        self.receivers = receivers
        self.flagged: list[tuple[int, int, str]] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_") and isinstance(node.value, ast.Name) and node.value.id in self.receivers:
            self.flagged.append((node.lineno, node.end_lineno or node.lineno, node.attr))
        self.generic_visit(node)


def is_exempt(lineno: int, end_lineno: int, comments: dict[int, str]) -> bool:
    """Return True if the flagged access is annotated on its own lines or the preceding line."""
    for line_num in range(lineno, end_lineno + 1):
        if ANNOTATION in comments.get(line_num, ""):
            return True

    return ANNOTATION in comments.get(lineno - 1, "")


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a sorted list of (1-based line number, attr name) for un-annotated flagged sites."""
    if not path.exists():
        print(f"WARNING: in-scope file not found: {path}", file=sys.stderr)
        return []

    source = path.read_text()
    tree = ast.parse(source)
    comments = extract_comments(source)

    alias_collector = AliasCollector()
    alias_collector.visit(tree)

    access_visitor = PrivateAccessVisitor(alias_collector.receivers)
    access_visitor.visit(tree)

    violations = [
        (lineno, attr)
        for lineno, end_lineno, attr in access_visitor.flagged
        if not is_exempt(lineno, end_lineno, comments)
    ]
    return sorted(violations)


def main() -> int:
    files = discover_files()
    return run_check(
        files,
        REPO_ROOT,
        check_file,
        summary="un-annotated coordinator-internal access(es) found",
        ok=f"no un-annotated coordinator-internal accesses found across {len(files)} test files.",
        footer=(
            f"Each site must carry a `{ANNOTATION}` comment, either trailing on the same\n"
            "line as the access or on the comment-only line immediately preceding it."
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
