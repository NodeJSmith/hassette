"""Extract entity properties from _attr_* annotations and CACHED_PROPERTIES_WITH_ATTR_."""

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedProperty:
    name: str
    python_type: str
    has_default: bool


def extract_properties(init_py: Path) -> list[ExtractedProperty]:
    """Extract _attr_* fields from the entity class in __init__.py."""
    source = init_py.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=str(init_py))
    except SyntaxError:
        return []

    entity_class = _find_entity_class(tree)
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

        if not has_default:
            if "None" not in type_str:
                type_str = f"{type_str} | None"

        properties.append(ExtractedProperty(name=field_name, python_type=type_str, has_default=has_default))

    return properties


def extract_cached_properties(init_py: Path) -> set[str]:
    """Extract the set of property names from CACHED_PROPERTIES_WITH_ATTR_."""
    source = init_py.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(init_py))
    except SyntaxError:
        return set()
    return _extract_cached_properties_set(tree)


def _find_entity_class(tree: ast.Module) -> ast.ClassDef | None:
    entity_bases = {"Entity", "ToggleEntity", "RestoreEntity"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            base_name = None
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if base_name in entity_bases:
                return node
    return None


def _extract_cached_properties_set(tree: ast.Module) -> set[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CACHED_PROPERTIES_WITH_ATTR_":
                    return _extract_set_literal(node.value)
    return set()


def _extract_set_literal(node: ast.expr) -> set[str]:
    result: set[str] = set()
    if isinstance(node, ast.Set):
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                result.add(elt.value)
    return result
