"""Generate __init__.py files by scanning all sibling modules via static analysis."""

import ast
from pathlib import Path


def generate_init_py(package_dir: Path) -> str:
    """Generate a complete __init__.py for a package by scanning all .py modules.

    Scans both generated and non-generated modules. Produces sorted imports
    and an __all__ list.
    """
    modules: dict[str, list[str]] = {}

    for py_file in sorted(package_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue

        module_name = py_file.stem
        exports = _extract_public_names(py_file)
        if exports:
            modules[module_name] = sorted(exports)

    import_lines: list[str] = []
    all_names: list[str] = []

    for module_name in sorted(modules):
        names = modules[module_name]
        all_names.extend(names)
        names_str = ", ".join(names)
        import_lines.append(f"from .{module_name} import {names_str}")

    lines = import_lines + [""]

    lines.append("__all__ = [")
    for name in sorted(all_names):
        lines.append(f'    "{name}",')
    lines.append("]")
    lines.append("")

    return "\n".join(lines)


def _extract_public_names(py_file: Path) -> list[str]:
    """Extract public class names, type aliases, and IntFlag enums from a module."""
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        return []

    names: list[str] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    if _is_type_alias_or_constant(node):
                        names.append(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
                if _is_type_alias_annotation(node):
                    names.append(node.target.id)

    return names


def _is_type_alias_or_constant(node: ast.Assign) -> bool:
    """Check if an assignment is a type alias (e.g., Flash = Literal[...]) or a module-level constant."""
    if isinstance(node.value, ast.Subscript):
        if isinstance(node.value.value, ast.Name) and node.value.value.id in ("Literal", "TypeAlias"):
            return True
    return False


def _is_type_alias_annotation(node: ast.AnnAssign) -> bool:
    """Check if an annotated assignment is a TypeAlias."""
    if isinstance(node.annotation, ast.Name) and node.annotation.id == "TypeAlias":
        return True
    return False
