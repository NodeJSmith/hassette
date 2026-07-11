#!/usr/bin/env python3
"""CI guard: detect un-annotated coordinator-internal accesses in migrated integration tests.

Companion to ``tools/check_internal_patches.py`` — same AST + tokenize-comment pattern,
applied to a structurally different problem. Spec 006 (``migrate-hassette-instance-fixture``)
migrated ``test_core.py``, ``test_fatal_shutdown.py``, and ``test_resource_deps.py`` off
private-attribute access on ``hassette_instance`` in favor of public properties. A small set
of sites have no public equivalent (state-machine internals, ``SessionManager`` internal
fields) and remain as private access, annotated ``# coordinator-internal`` to mark them as a
deliberate, reviewed exception rather than undetected drift.

Scope: three test files.

    * ``tests/integration/test_core.py``
    * ``tests/integration/test_fatal_shutdown.py``
    * ``tests/integration/test_resource_deps.py``

``tests/integration/conftest.py`` is DELIBERATELY OUT OF SCOPE — its
``cleanup_hassette_streams()`` helper accesses ``instance._event_stream_service`` and
``instance._bus_service`` directly by design; it is test infrastructure that owns the
teardown, not a test asserting behavior against the coordinator.

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
accepted, mirroring ``check_internal_patches.py``:

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

from lint_helpers import extract_comments

REPO_ROOT = Path(__file__).resolve().parent.parent

IN_SCOPE_FILES: list[Path] = [
    REPO_ROOT / "tests" / "integration" / "test_core.py",
    REPO_ROOT / "tests" / "integration" / "test_fatal_shutdown.py",
    REPO_ROOT / "tests" / "integration" / "test_resource_deps.py",
]

# The Hassette fixture instance. Every local alias of its ``session_manager`` property is
# added to this set on a per-module basis by AliasCollector before the access scan runs.
BASE_RECEIVER = "hassette_instance"

ANNOTATION = "# coordinator-internal"


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
    all_violations: list[tuple[Path, int, str]] = []

    for path in IN_SCOPE_FILES:
        rel = path.relative_to(REPO_ROOT)
        for lineno, attr in check_file(path):
            all_violations.append((rel, lineno, attr))

    if all_violations:
        print(f"ERROR: {len(all_violations)} un-annotated coordinator-internal access(es) found:")
        print()
        for rel, lineno, attr in all_violations:
            print(f"  {rel}:{lineno} — {attr}")
        print()
        print(f"Each site must carry a `{ANNOTATION}` comment, either trailing on the same")
        print("line as the access or on the comment-only line immediately preceding it.")
        print("See design/specs/006-migrate-hassette-instance-fixture/design.md for the")
        print("private-attribute-access requirements this check enforces.")
        return 1

    total_files = len(IN_SCOPE_FILES)
    print(f"OK: no un-annotated coordinator-internal accesses found across {total_files} in-scope test files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
