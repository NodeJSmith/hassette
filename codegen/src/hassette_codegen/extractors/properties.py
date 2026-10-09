"""Extract entity properties from the _attr_* annotations on a domain's entity class."""

import ast
from dataclasses import dataclass
from pathlib import Path

from hassette_codegen.extractors._common import find_entity_class


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
    source = entity_module.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=str(entity_module))
    except SyntaxError:
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
