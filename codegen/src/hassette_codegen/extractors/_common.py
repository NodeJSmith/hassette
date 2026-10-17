"""Shared AST utilities for entity extraction."""

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import TypeVar

ENTITY_BASES = {"Entity", "ToggleEntity", "RestoreEntity"}

T = TypeVar("T")


def find_entity_class(tree: ast.Module) -> ast.ClassDef | None:
    """Find the first class inheriting from an HA entity base class."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            base_name = None
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if base_name in ENTITY_BASES:
                return node
    return None


def parse_module_or_none(filepath: Path) -> ast.Module | None:
    """Parse a Python source file into an AST module, tolerating an unreadable file or a ``SyntaxError``.

    Every extractor reads an upstream Home Assistant source file that may be unreadable
    (permissions, a partial checkout) or fail to parse (an unexpected format change), and each
    must treat that as "nothing found" rather than propagate the exception.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(filepath))
    except (OSError, SyntaxError):
        return None


def iter_classdef_literal_members(
    node: ast.ClassDef, literal_type: type[T], *, skip_private: bool = False
) -> Iterator[tuple[str, T]]:
    """Yield ``(name, value)`` for each simple ``NAME = <literal>`` assignment in a class body.

    Only assignments whose value is a constant of ``literal_type`` are yielded; an assignment with
    several ``Name`` targets yields once per target. ``skip_private=True`` drops names starting
    with ``_``.
    """
    for item in node.body:
        if not isinstance(item, ast.Assign):
            continue
        if not (isinstance(item.value, ast.Constant) and isinstance(item.value.value, literal_type)):
            continue
        value = item.value.value
        for target in item.targets:
            if not isinstance(target, ast.Name):
                continue
            if skip_private and target.id.startswith("_"):
                continue
            yield target.id, value
