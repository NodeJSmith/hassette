"""Shared AST utilities for entity extraction."""

import ast

ENTITY_BASES = {"Entity", "ToggleEntity", "RestoreEntity"}


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
