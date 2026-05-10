"""Extract IntFlag enums from HA core component files."""

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedEnum:
    name: str
    members: list[tuple[str, int]]


def extract_features(component_dir: Path) -> list[ExtractedEnum]:
    """Extract IntFlag enums from both const.py and __init__.py."""
    results: list[ExtractedEnum] = []
    seen_names: set[str] = set()

    for filename in ("const.py", "__init__.py"):
        filepath = component_dir / filename
        if not filepath.exists():
            continue

        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.endswith("EntityFeature"):
                continue
            if not _is_intflag_subclass(node):
                continue
            if node.name in seen_names:
                continue

            members = _extract_enum_members(node)
            if members:
                results.append(ExtractedEnum(name=node.name, members=members))
                seen_names.add(node.name)

    return results


def _is_intflag_subclass(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "IntFlag":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "IntFlag":
            return True
    return False


def _extract_enum_members(node: ast.ClassDef) -> list[tuple[str, int]]:
    members: list[tuple[str, int]] = []
    for item in node.body:
        if not isinstance(item, ast.Assign):
            continue
        for target in item.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id.startswith("_"):
                continue
            if isinstance(item.value, ast.Constant) and isinstance(item.value.value, int):
                members.append((target.id, item.value.value))
    return members
