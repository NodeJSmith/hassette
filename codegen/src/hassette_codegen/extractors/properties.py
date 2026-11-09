"""Extract entity properties from the _attr_* annotations on a domain's entity class."""

import ast
from dataclasses import dataclass
from pathlib import Path

from hassette_codegen.extractors._common import find_entity_class, parse_module_or_none

DEPRECATED_ATTR_ALIAS = "DeprecatedEntityAttr"
"""HA's marker for a renamed `_attr_*` kept as an alias to its replacement, which the class also declares."""


@dataclass
class ExtractedProperty:
    name: str
    python_type: str
    has_default: bool
    union_mode: str | None = None
    validation_aliases: tuple[str, ...] = ()
    """Wire keys accepted for this field, in priority order. Empty means the field name is the wire key."""


def extract_properties(entity_module: Path) -> list[ExtractedProperty]:
    """Extract _attr_* fields from the entity class defined in ``entity_module``."""
    tree = parse_module_or_none(entity_module)
    if tree is None:
        return []

    entity_class = find_entity_class(tree)
    if entity_class is None:
        return []

    properties: list[ExtractedProperty] = []
    for node in entity_class.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        if not node.target.id.startswith("_attr_"):
            continue

        if is_deprecated_attr_alias(node.value):
            continue

        field_name = node.target.id[6:]  # strip "_attr_"

        if field_name == "supported_features":
            continue

        type_str = ast.unparse(node.annotation)

        if type_str == "None":
            continue

        has_default = node.value is not None

        if "None" not in type_str:
            type_str = f"{type_str} | None"

        properties.append(ExtractedProperty(name=field_name, python_type=type_str, has_default=has_default))

    return properties


def is_deprecated_attr_alias(value: ast.expr | None) -> bool:
    """Whether ``value`` is ``DeprecatedEntityAttr[T](...)``, an alias for a renamed attribute."""
    if not isinstance(value, ast.Call):
        return False

    callee = value.func
    if isinstance(callee, ast.Subscript):  # DeprecatedEntityAttr[T](...) -> DeprecatedEntityAttr
        callee = callee.value

    if isinstance(callee, ast.Attribute):  # deprecation.DeprecatedEntityAttr
        return callee.attr == DEPRECATED_ATTR_ALIAS
    return isinstance(callee, ast.Name) and callee.id == DEPRECATED_ATTR_ALIAS
