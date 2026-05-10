"""Determine the correct state base class for a domain via AST heuristics."""

import ast
from pathlib import Path

from hassette_codegen.extractors._common import find_entity_class


def determine_base_class(init_py: Path) -> str:
    """Determine the state base class for an entity domain.

    Heuristic:
    - ToggleEntity in bases → BoolBaseState
    - state property returns float|None or int|None → NumericBaseState
    - Otherwise → StringBaseState
    """
    source = init_py.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=str(init_py))
    except SyntaxError:
        return "StringBaseState"

    entity_class = find_entity_class(tree)
    if entity_class is None:
        return "StringBaseState"

    if _has_toggle_entity_base(entity_class):
        return "BoolBaseState"

    if _has_numeric_state_return(entity_class):
        return "NumericBaseState"

    return "StringBaseState"


def _has_toggle_entity_base(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "ToggleEntity":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "ToggleEntity":
            return True
    return False


def _has_numeric_state_return(cls: ast.ClassDef) -> bool:
    """Check if the entity's state property returns a numeric type."""
    for node in cls.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "state":
            continue

        is_property = any(
            (isinstance(d, ast.Name) and d.id == "property") or (isinstance(d, ast.Attribute) and d.attr == "property")
            for d in node.decorator_list
        )
        if not is_property:
            continue

        if node.returns is None:
            continue

        return_str = ast.unparse(node.returns)
        numeric_indicators = {"float", "int", "Decimal"}
        for indicator in numeric_indicators:
            if indicator in return_str:
                return True

    return False
