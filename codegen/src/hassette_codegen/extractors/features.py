"""Extract IntFlag and StrEnum classes from HA core component files."""

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hassette_codegen.extractors._common import iter_classdef_literal_members, parse_module_or_none


@dataclass
class ExtractedEnum:
    name: str
    members: Sequence[tuple[str, int | str]]
    kind: str = "IntFlag"


def extract_features(component_dir: Path) -> list[ExtractedEnum]:
    """Extract IntFlag enums (EntityFeature classes) from both const.py and __init__.py."""
    results: list[ExtractedEnum] = []
    seen_names: set[str] = set()

    for filename in ("const.py", "__init__.py"):
        filepath = component_dir / filename
        if not filepath.exists():
            continue

        tree = parse_module_or_none(filepath)
        if tree is None:
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

        tree = parse_module_or_none(filepath)
        if tree is None:
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
    return list(iter_classdef_literal_members(node, int, skip_private=True))


def _extract_str_members(node: ast.ClassDef) -> list[tuple[str, str]]:
    return list(iter_classdef_literal_members(node, str, skip_private=True))
