"""Move lazy imports to module top in test files.

For each file:
1. Parse AST to find imports inside function bodies
2. Collect unique import statements
3. Check which are already at module top (skip those)
4. Remove inline imports from function bodies
5. Add missing imports after the last existing top-level import
"""

import ast
import sys
from pathlib import Path


def get_module_level_imports(source: str) -> set[str]:
    """Get all module-level import names (including TYPE_CHECKING)."""
    tree = ast.parse(source)
    names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        # Also check TYPE_CHECKING blocks
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Attribute) and isinstance(test.value, ast.Name):
                if test.value.id == "typing" and test.attr == "TYPE_CHECKING":
                    for child in ast.walk(node):
                        if isinstance(child, (ast.Import, ast.ImportFrom)):
                            for alias in child.names:
                                names.add(alias.asname or alias.name)
            elif isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        for alias in child.names:
                            names.add(alias.asname or alias.name)
    return names


def find_lazy_imports(source: str) -> list[tuple[int, str, str]]:
    """Find imports inside function bodies. Returns (lineno, import_line, imported_names_key)."""
    tree = ast.parse(source)
    lines = source.splitlines()
    results = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if not isinstance(child, (ast.Import, ast.ImportFrom)):
                continue
            lineno = child.lineno
            line = lines[lineno - 1]
            # Build a normalized import statement for deduplication
            if isinstance(child, ast.ImportFrom):
                names = ", ".join(sorted(a.name for a in child.names))
                key = f"from {child.module} import {names}"
            else:
                names = ", ".join(sorted(a.name for a in child.names))
                key = f"import {names}"
            results.append((lineno, line, key))

    return results


def find_last_import_line(source: str) -> int:
    """Find the line number of the last module-level import statement."""
    tree = ast.parse(source)
    last_import = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import = node.end_lineno or node.lineno
        # Include TYPE_CHECKING block
        if isinstance(node, ast.If):
            test = node.test
            is_tc = False
            if isinstance(test, ast.Attribute) and isinstance(test.value, ast.Name):
                is_tc = test.value.id == "typing" and test.attr == "TYPE_CHECKING"
            elif isinstance(test, ast.Name):
                is_tc = test.id == "TYPE_CHECKING"
            if is_tc:
                last_import = node.end_lineno or node.lineno
    return last_import


def process_file(path: Path, dry_run: bool = False) -> int:
    source = path.read_text()
    existing = get_module_level_imports(source)
    lazy = find_lazy_imports(source)

    if not lazy:
        return 0

    # Collect unique imports that need to be added at module top
    to_add: dict[str, str] = {}  # key -> normalized import statement
    lines_to_remove: set[int] = set()

    for lineno, _line, key in lazy:
        lines_to_remove.add(lineno)
        # For multi-line imports, also remove continuation lines
        src_lines = source.splitlines()
        if "(" in src_lines[lineno - 1] and ")" not in src_lines[lineno - 1]:
            for j in range(lineno, len(src_lines)):
                lines_to_remove.add(j + 1)
                if ")" in src_lines[j]:
                    break
        # Check if all names from this import are already at module level
        # Parse the key (normalized form) to extract names
        parts = key.split(" import ")
        if len(parts) == 2:
            names = [n.strip() for n in parts[1].split(",")]
            if all(n in existing for n in names):
                continue  # Already imported at module level
        if key not in to_add:
            to_add[key] = key
            for n in names:
                existing.add(n)

    if not lines_to_remove and not to_add:
        return 0

    lines = source.splitlines()

    # Remove lazy import lines (and blank line after if it creates a double blank)
    new_lines = []
    skip_next_blank = False
    for i, line in enumerate(lines, 1):
        if i in lines_to_remove:
            # If next line is blank and prev line is blank or func def, skip next blank too
            if i < len(lines) and lines[i].strip() == "":
                skip_next_blank = True
            continue
        if skip_next_blank and line.strip() == "":
            skip_next_blank = False
            continue
        skip_next_blank = False
        new_lines.append(line)

    # Add new imports at module top
    if to_add:
        insert_after = find_last_import_line("\n".join(new_lines))
        import_block = "\n".join(sorted(to_add.values()))
        # Insert after the last import line
        new_lines.insert(insert_after, import_block)

    result = "\n".join(new_lines)
    if not result.endswith("\n"):
        result += "\n"

    if dry_run:
        print(f"{path}: would remove {len(lines_to_remove)} lazy imports, add {len(to_add)} at top")
        return len(lines_to_remove)

    path.write_text(result)
    print(f"{path}: removed {len(lines_to_remove)} lazy imports, added {len(to_add)} at top")
    return len(lines_to_remove)


def main():
    dry_run = "--dry-run" in sys.argv
    total = 0
    for root_dir in ["tests"]:
        for path in sorted(Path(root_dir).rglob("*.py")):
            total += process_file(path, dry_run)
    print(f"\nTotal: {total} lazy imports {'would be ' if dry_run else ''}fixed")


if __name__ == "__main__":
    main()
