"""Extract IntFlag and StrEnum classes from HA core component files."""

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedEnum:
    name: str
    members: list[tuple[str, int | str]]
    kind: str = "IntFlag"


def extract_features(component_dir: Path) -> list[ExtractedEnum]:
    """Extract IntFlag enums (EntityFeature classes) from both const.py and __init__.py."""
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

            members = _extract_int_members(node)
            if members:
                results.append(ExtractedEnum(name=node.name, members=members, kind="IntFlag"))
                seen_names.add(node.name)

    return results


def extract_strenum(component_dir: Path) -> list[ExtractedEnum]:
    """Extract StrEnum classes from both const.py and __init__.py."""
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
            if not _is_strenum_subclass(node):
                continue
            if node.name.endswith("EntityFeature"):
                continue
            if node.name in seen_names:
                continue

            members = _extract_str_members(node)
            if members:
                results.append(ExtractedEnum(name=node.name, members=members, kind="StrEnum"))
                seen_names.add(node.name)

    return results


def _is_intflag_subclass(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "IntFlag":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "IntFlag":
            return True
    return False


def _is_strenum_subclass(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "StrEnum":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "StrEnum":
            return True
    return False


def _extract_int_members(node: ast.ClassDef) -> list[tuple[str, int]]:
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


def _extract_str_members(node: ast.ClassDef) -> list[tuple[str, str]]:
    members: list[tuple[str, str]] = []
    for item in node.body:
        if not isinstance(item, ast.Assign):
            continue
        for target in item.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id.startswith("_"):
                continue
            if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                members.append((target.id, item.value.value))
    return members
