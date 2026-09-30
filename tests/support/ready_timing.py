"""Locate where a resource class calls ``mark_ready(self, ...)``.

``mark_ready()`` timing depends on the resource's shape (see ``.claude/rules/resource-lifecycle.md``):
a resource with no background loop marks itself ready in an init hook, a ``Service`` with a ``serve()``
loop marks ready once that loop is running. These helpers read the class source, so the check covers
every production resource without having to stand up each one's runtime dependencies.
"""

import ast
import inspect
import textwrap
from pathlib import Path


def mark_ready_methods(class_node: ast.ClassDef) -> frozenset[str]:
    """Return the names of the class's own methods whose bodies call ``mark_ready(self, ...)``.

    Calls inside nested functions are attributed to the enclosing method. Calls that mark a
    different object ready (e.g. ``mark_ready(inst)``) are ignored. Only the unqualified call form is
    matched, which is how every call site imports it from ``hassette.resources.lifecycle``; a
    ``lifecycle.mark_ready(self)`` call would be missed.
    """
    found: set[str] = set()
    for method in class_node.body:
        if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in ast.walk(method):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "mark_ready"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "self"
            ):
                found.add(method.name)
                break
    return frozenset(found)


def assert_marks_ready_in(cls: type, *expected_methods: str) -> None:
    """Assert ``cls`` calls ``mark_ready(self, ...)`` from exactly ``expected_methods``."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    class_node = tree.body[0]
    assert isinstance(class_node, ast.ClassDef)
    actual = mark_ready_methods(class_node)
    assert actual == frozenset(expected_methods), (
        f"{cls.__name__} calls mark_ready(self) from {sorted(actual)}, expected {sorted(expected_methods)}"
    )


def find_mark_ready_classes(source_root: Path) -> set[str]:
    """Return the names of every class under ``source_root`` that calls ``mark_ready(self, ...)``."""
    names: set[str] = set()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and mark_ready_methods(node):
                names.add(node.name)
    return names
